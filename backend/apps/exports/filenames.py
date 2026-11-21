"""FX-2 (item 13): the downloaded PDF's file name - FlexiDriveMy_{brand}-{model}_{tenure}m_{YYYY-MM-DD}.pdf,
ASCII only (it used to be comparison_report_{job id}.pdf). The date is the Malaysia date of the export."""

import re
import unicodedata

from django.utils import timezone

LEGACY_NAME = "comparison_report_{job_id}.pdf"
# Separates the stored file's own unique name from the download name kept after it (no extra database field).
STORED_NAME_SEPARATOR = "__"


def _ascii_slug(text):
    ascii_text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-")


def pdf_download_name(vehicle, tenure_months, on_date=None):
    day = on_date or timezone.localdate()
    car = "-".join(part for part in (_ascii_slug(vehicle.brand.name), _ascii_slug(vehicle.name)) if part)
    return f"FlexiDriveMy_{car}_{int(tenure_months)}m_{day:%Y-%m-%d}.pdf"


def download_name_from_stored_path(file_path, job_id):
    """The name save_pdf kept after STORED_NAME_SEPARATOR, else the legacy name (jobs stored before FX-2)."""
    base = str(file_path).replace("\\", "/").rsplit("/", 1)[-1]
    if STORED_NAME_SEPARATOR in base:
        name = base.split(STORED_NAME_SEPARATOR, 1)[1]
        if re.fullmatch(r"[A-Za-z0-9._-]+\.pdf", name):
            return name
    return LEGACY_NAME.format(job_id=job_id)
