import csv
import io

from openpyxl import load_workbook

from .models import Brand

# engine_capacity_kw is POWER OUTPUT in kW (legacy column name, see
# VehicleModel). powertrain is a required column; engine_capacity_cc is
# optional at the file level because a BEV row legitimately has none - the
# per-row cc-vs-powertrain rule is VehicleModelSerializer's job, so a bad
# row shows up in the row report without blocking the valid ones.
REQUIRED_COLUMNS = {"brand", "name", "trim", "body_segment", "msrp", "engine_capacity_kw", "powertrain"}
# road_tax_class is optional: a blank cell means the body type's default
# (VehicleModel.save()), so an SUV row is costed as non-saloon with no extra column.
OPTIONAL_COLUMNS = {"engine_capacity_cc", "model_year", "thumbnail_url", "road_tax_class"}


class StructuralImportError(Exception):
    """A batch-level problem (e.g. a missing required column, or a file
    that can't be parsed at all) — the whole upload is rejected, nothing
    is validated or committed row-by-row."""


def parse_upload(uploaded_file):
    """Parse a CSV or XLSX upload into a list of {column: value} row dicts.

    Raises StructuralImportError for an unsupported/corrupt file or a
    missing required column — both reject the entire batch before any
    row is individually validated. Column names are matched case-
    insensitively (QA audit M2: "Brand" was rejected even though "brand"
    worked) - every returned row dict is keyed by lowercased column name.
    """
    filename = (uploaded_file.name or "").lower()
    if filename.endswith(".csv"):
        rows = _parse_csv(uploaded_file)
    elif filename.endswith(".xlsx"):
        rows = _parse_xlsx(uploaded_file)
    else:
        raise StructuralImportError("Unsupported file type. Upload a .csv or .xlsx file.")

    if not rows:
        return []

    header = {key for key in rows[0].keys() if key}
    missing = REQUIRED_COLUMNS - header
    if missing:
        raise StructuralImportError(f"Missing required column(s): {', '.join(sorted(missing))}")

    return rows


def _lowercase_keys(row):
    return {(key.strip().lower() if isinstance(key, str) else key): value for key, value in row.items()}


def _parse_csv(uploaded_file):
    raw_bytes = uploaded_file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        # QA audit M2: Excel's own default CSV export on Windows is
        # Windows-1252 (cp1252), not UTF-8 - a file with e.g. an accented
        # brand name saved that way isn't valid UTF-8 and crashed the
        # whole import. cp1252 maps every single byte value to some
        # character, so this fallback itself essentially never raises -
        # if the file is garbage in some OTHER way, the row/column
        # checks below still catch it.
        text = raw_bytes.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text))
    return [_lowercase_keys(row) for row in reader]


def _parse_xlsx(uploaded_file):
    try:
        workbook = load_workbook(uploaded_file, read_only=True, data_only=True)
    except Exception as exc:
        # QA audit M2: a corrupt/truncated .xlsx (or any non-.xlsx file
        # just renamed with that extension) raises one of several
        # openpyxl/zipfile-internal exception types depending on exactly
        # how it's malformed - none of them meaningful to an end user,
        # and previously uncaught (an unhandled 500).
        raise StructuralImportError(
            "Couldn't read this file as a valid .xlsx workbook. It may be corrupted "
            "or not actually an Excel file."
        ) from exc

    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return []
    header = [str(cell).strip().lower() if cell is not None else "" for cell in header_row]

    rows = []
    for raw_row in rows_iter:
        if all(cell is None for cell in raw_row):
            continue
        row = {header[i]: raw_row[i] for i in range(len(header)) if i < len(raw_row)}
        rows.append(row)
    return rows


def normalize_row(row):
    """Resolve human-entered CSV/Excel values into what VehicleModelSerializer
    expects (brand name -> brand id; blank optional fields -> omitted).

    Returns (data, error). error is a DRF-style field-error dict, or None.
    """
    data = {}
    for key, value in row.items():
        if key in REQUIRED_COLUMNS | OPTIONAL_COLUMNS:
            data[key] = value.strip() if isinstance(value, str) else value

    brand_name = (data.get("brand") or "").strip() if isinstance(data.get("brand"), str) else data.get("brand")
    if not brand_name:
        return None, {"brand": ["This field is required."]}

    brand = Brand.objects.filter(name__iexact=str(brand_name), is_active=True).first()
    if brand is None:
        return None, {"brand": [f"Brand '{brand_name}' not found or inactive."]}
    data["brand"] = brand.pk

    for optional_field in OPTIONAL_COLUMNS:
        if data.get(optional_field) in ("", None):
            data.pop(optional_field, None)

    # Spreadsheet-friendly spellings ("Mild Hybrid", "mild-hybrid") map to
    # the stored value ("mild_hybrid"). Anything else still fails the
    # serializer's choice check - nothing is guessed.
    # Same for the road-tax class ("Non-saloon", "non saloon" -> "non_saloon").
    for spelled_field in ("powertrain", "road_tax_class"):
        if isinstance(data.get(spelled_field), str):
            data[spelled_field] = data[spelled_field].strip().lower().replace(" ", "_").replace("-", "_")

    return data, None
