"""Run 2 fix batch 1 (Master Test Run 2, check A12): the exported PDF's chart is
readable and the PDF carries the rest of the TCO tab.

Real WeasyPrint compilation, through the real export endpoint. The chart is the
REAL Recharts chart, rendered by the frontend at the 943px width of the bug
report from the dev database's own BMW 320i / Macan Electric forecasts
(tests/fixtures/negative_equity_*_60.svg), with its CSS-variable paints resolved
to the colours the browser draws - exactly what ExportPdfButton's capture sends.

The BMW goldens are for the fixture car at the reference price RM 265,800 (26,580
down, gross RM 338,397.80): net RM 201,011.80, age -RM 108,881.53, mileage
-RM 19,532.47, predicted RM 137,386.00. The live catalog car is RM 267,800, so its
figures differ (predicted 138,419.76 - the same curve scaled to its price). They come from the deployed log-linear model, so the fixture
refits that model the way run 10 was fitted (same data, same 80/20 split,
random_state 42). The rest are independent of any model.

Run 3 fix batch 6: the standard band is now modelled at 12,500 km a year (was
15,000), so the model reads less mileage and the BMW keeps more value; the new
goldens were computed by the independent Run 3 oracle (run3_qa/oracle.py) - the old
ones were net 203,742.51, age -107,914.03, mileage -23,230.68, predicted 134,655.29.
"""

import importlib
import io
import re
from decimal import Decimal
from pathlib import Path

import joblib
import numpy as np
import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient
from sklearn.model_selection import train_test_split

from apps.exports import tasks
from apps.exports.pdf import render_pdf_with_timeout
from apps.ml import training
from apps.ml.features import feature_frame
from apps.ml.log_linear import LogLinearDepreciationModel
from apps.ml.models import ModelType, PredictionTarget, ProductionModel
from apps.policy.models import InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel

try:
    import weasyprint
except Exception as exc:  # native GObject/Pango libraries missing (OSError, not ImportError)
    pytest.skip(f"weasyprint is not usable in this environment: {exc}", allow_module_level=True)
try:
    import pypdf
except ImportError as exc:
    pytest.skip(f"pypdf not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_DATASET = Path(__file__).resolve().parents[2] / "ml" / "data" / "real_historical_pricing.csv"
seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")

# What ExportPdfButton.captureChartSvg writes onto the clone: the colour the
# browser drew for each CSS variable (Tailwind v4: indigo-600, red-600, slate-200, slate-500).
RESOLVED_PAINTS = {
    "var(--color-primary-600)": "rgb(79, 57, 246)",
    "var(--color-danger-600)": "rgb(231, 0, 11)",
    "var(--color-danger-700)": "rgb(193, 0, 7)",
    "var(--color-border)": "rgb(226, 232, 240)",
    "var(--color-ink-muted)": "rgb(98, 116, 142)",
}


def captured_chart(name):
    svg = (FIXTURES / name).read_text(encoding="utf-8")
    for variable, rgb in RESOLVED_PAINTS.items():
        svg = svg.replace(variable, rgb)
    assert "var(" not in svg
    return svg


def raw_text(pdf_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def flat_text(pdf_bytes):
    return " ".join(raw_text(pdf_bytes).split())


def page_count(pdf_bytes):
    return len(pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


def stroke_colours(pdf_bytes):
    """Every stroke colour (RG operator) in the first page's drawing, as '#rrggbb'."""
    page = pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages[0]
    chunks, seen = [page.get_contents().get_data().decode("latin-1")], set()
    for xobject in (page.get("/Resources", {}).get("/XObject", {}) or {}).values():
        form = xobject.get_object()
        if id(form) not in seen and form.get("/Subtype") == "/Form":
            seen.add(id(form))
            chunks.append(form.get_data().decode("latin-1"))
    found = set()
    for r, g, b in re.findall(r"([\d.]+) ([\d.]+) ([\d.]+) RG\b", "\n".join(chunks)):
        found.add("#%02x%02x%02x" % tuple(round(float(v) * 255) for v in (r, g, b)))
    return found


# --- data ---------------------------------------------------------------------------------


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


@pytest.fixture
def bmw():
    brand = Brand.objects.create(name="BMW", tier_code="2")
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brand, rate_percent="2.8000", is_active=True)
    return VehicleModel.objects.create(
        brand=brand, name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN, msrp="265800.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )


@pytest.fixture
def macan_electric():
    brand = Brand.objects.create(name="Porsche", tier_code="1")
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brand, rate_percent="3.5000", is_active=True)
    return VehicleModel.objects.create(
        brand=brand, name="Macan Electric", trim="Macan RWD", body_segment=BodySegment.SUV, msrp="575000.00",
        engine_capacity_kw="261.10", powertrain="bev",
    )


@pytest.fixture
def run10_model(tmp_path):
    """The log-linear model run 10 deployed, refitted the same way."""
    with open(REAL_DATASET, "rb") as dataset:
        df = training.load_and_validate_csv(dataset)
    X_train, _, y_train, _, keys_train, _ = train_test_split(
        feature_frame(df), np.log(df["resale_price"].astype(float)), df["model_key"], test_size=0.2, random_state=42
    )
    model = LogLinearDepreciationModel().fit(X_train, y_train, list(keys_train))
    path = tmp_path / "run10_log_linear.joblib"
    joblib.dump(model, path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.LOG_LINEAR
    production.model_file_path = str(path)
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.save()
    return model


@pytest.fixture
def compiled_html(monkeypatch):
    """The HTML each export compiled (the real compile still runs)."""
    seen = []

    def _record(html, timeout_seconds):
        seen.append(html)
        return render_pdf_with_timeout(html, timeout_seconds)

    monkeypatch.setattr(tasks, "render_pdf_with_timeout", _record)
    return seen


def export(client, vehicle, *, downpayment="26580.00", tenure=60, chart_svg="", band="standard"):
    response = client.post(
        "/api/exports/pdf/",
        {"vehicle": vehicle.pk, "tenure_months": tenure, "mileage_band": band, "downpayment": downpayment,
         "chart_svg": chart_svg},
        format="json",
    )
    assert response.status_code == 200, getattr(response, "data", response.content[:200])
    assert response.content.startswith(b"%PDF-")
    return response.content


# --- BMW 320i, 60 months, standard band, 10% down, NCD 0 -------------------------------------


def test_the_chart_labels_and_legend_are_in_the_pdf(client, bmw, run10_model):
    pdf = export(client, bmw, chart_svg=captured_chart("negative_equity_bmw_60.svg"))

    lines = raw_text(pdf).splitlines()
    for label in ("0mo", "60mo", "RM 0", "RM 70k", "RM 280k"):
        assert label in lines, f"axis label {label!r} missing from the PDF"
    text = flat_text(pdf)
    assert "Remaining loan vs. predicted car value" in text
    assert "Predicted resale value against the outstanding Hire Purchase balance over the 60-month term." in text
    assert "Amount to settle (estimate)" in text and "Predicted resale value" in text
    assert "Your lender's settlement letter is the final figure." in text


def test_both_lines_keep_their_screen_colours_and_nothing_falls_back_to_grey(client, bmw, run10_model):
    pdf = export(client, bmw, chart_svg=captured_chart("negative_equity_bmw_60.svg"))

    colours = stroke_colours(pdf)
    assert {"#4f39f6", "#e7000b"} <= colours  # resale (indigo) and amount to settle (red)
    assert "#444444" not in colours  # the sanitizer's "unresolved colour" grey never appears


def test_an_unresolved_css_variable_shows_as_grey_never_black(client, bmw, run10_model):
    unresolved = (FIXTURES / "negative_equity_bmw_60.svg").read_text(encoding="utf-8")  # still var(...)

    pdf = export(client, bmw, chart_svg=unresolved)

    colours = stroke_colours(pdf)
    assert "#444444" in colours and "#4f39f6" not in colours
    assert "#000000" not in colours


def test_every_figure_from_the_tco_tab_is_in_the_bmw_pdf(client, bmw, run10_model):
    pdf = export(client, bmw, chart_svg=captured_chart("negative_equity_bmw_60.svg"))

    text = flat_text(pdf)
    for expected in (
        "RM 4,545.18",      # monthly HP instalment
        "RM 338,397.80",    # TCO gross
        "RM 201,011.80",    # TCO net
        "RM 379.00", "RM 4,784.40", "RM 2,658.00",  # road tax, insurance, maintenance a year
        "-RM 108,881.53",   # age
        "-RM 19,532.47",    # mileage
        "RM 137,386.00",    # predicted resale value
        "RM 196,280.44",    # to settle after 12 months
        "RM 127,476.28",    # to settle at month 30 (half term)
        "RM 0.50 / km",     # excess mileage charge
    ):
        assert expected in text, f"{expected} missing from the PDF"
    for heading in ("60-month total cost of ownership", "Running costs a year", "Why this predicted value?",
                    "Contract return checklist", "Total cost of ownership by pathway"):
        assert heading in text
    assert "No penalty under the reducing-balance method." in text
    assert "1,998 cc petrol, saloon - JPJ cc schedule" in text  # the basis line
    assert "Insurance shown before No-Claim Discount." in text  # NCD 0
    assert "Estimates for Peninsular Malaysia, private car; insurance and maintenance are planning assumptions" in text
    assert "Net TCO credits your estimated equity at month 60" in text
    assert "How much each factor moved the value from the new price" in text


def test_factors_that_are_exactly_zero_are_left_out(client, bmw, run10_model):
    text = flat_text(export(client, bmw, chart_svg=captured_chart("negative_equity_bmw_60.svg")))

    assert "+RM 0.00" not in text and "-RM 0.00" not in text
    for zero_factor in ("Brand tier", "Engine size", "Body type", "Recond import"):
        assert zero_factor not in text
    assert "Age -RM 108,881.53" in text and "Mileage -RM 19,532.47" in text


def test_the_rate_has_two_decimals_and_the_time_is_malaysia_time(client, bmw, run10_model):
    text = flat_text(export(client, bmw))

    assert "Flat rate (p.a.): 2.80%" in text
    assert "2.8000%" not in text
    assert re.search(r"Generated on \d{2} \w+ \d{4}, \d{2}:\d{2} MYT", text)


def test_money_stays_on_one_line_and_tables_are_not_split(client, bmw, run10_model):
    pdf = export(client, bmw, chart_svg=captured_chart("negative_equity_bmw_60.svg"))

    raw = raw_text(pdf)
    assert "RM 338,397.80" in raw and "RM 299,290.80" in raw  # not "RM" / "338,397.80" on two lines
    assert not re.search(r"RM\n[\d,]+\.\d\d", raw)
    # the TCO-by-pathway table is one piece: its header is printed once, not repeated after one row
    assert flat_text(pdf).count("What you get back") == 1


def test_a_wide_chart_is_scaled_into_the_page_instead_of_running_off_it(client, bmw, run10_model, compiled_html):
    export(client, bmw, chart_svg=captured_chart("negative_equity_bmw_60.svg"))
    html = compiled_html[-1]

    def chart_box(source):
        document = weasyprint.HTML(string=source).render()
        page_box = document.pages[0]._page_box
        content_right = page_box.margin_left + page_box.width
        for box in page_box.descendants():
            if str(getattr(box, "element_tag", "")).endswith("svg"):
                return box.position_x, box.position_x + box.width, box.width, content_right
        raise AssertionError("the chart was not drawn")

    left, right, width, content_right = chart_box(html)
    assert width < 943 and right <= content_right + 0.5  # inside the column, on page 1
    # the guard is sensitive: without the CSS rule the same chart is its full 943px and overruns
    _, bad_right, bad_width, _ = chart_box(html.replace(".chart svg { width: 100%; height: auto; }", ""))
    assert bad_width == 943 and bad_right > content_right


def test_the_chart_block_is_kept_together_with_its_title_and_legend(client, bmw, run10_model, compiled_html):
    export(client, bmw, chart_svg=captured_chart("negative_equity_bmw_60.svg"))
    html = compiled_html[-1]

    assert ".chart { margin: 0.6em 0; text-align: center; page-break-inside: avoid; }" in html
    assert ".chart-block { page-break-inside: avoid;" in html
    assert "tr { page-break-inside: avoid; }" in html
    assert "h3.section" in html and "page-break-after: avoid" in html
    assert "td.num { white-space: nowrap; }" in html


# --- exports without a chart, and without a TCO ----------------------------------------------------


def test_an_export_from_the_financing_pathways_tab_has_no_chart_block_but_keeps_the_tco_sections(
    client, bmw, run10_model, compiled_html
):
    pdf = export(client, bmw, chart_svg="")

    text = flat_text(pdf)
    assert 'class="chart"' not in compiled_html[-1]
    assert "Remaining loan vs. predicted car value" not in text
    assert "Amount to settle (estimate)" not in text.replace("Amount to settle (estimate):", "")  # no legend
    assert "RM 4,545.18" in text and "Running costs a year" in text and "Contract return checklist" in text


def test_a_car_the_tco_cannot_be_built_for_still_exports_and_says_why_once(client, compiled_html):
    brand = Brand.objects.create(name="NoSpecs", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000", is_active=True)
    car = VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN, msrp="100000.00",
        engine_capacity_kw="90.00",  # no powertrain / cc: running costs cannot be worked out
    )

    pdf = export(client, car, downpayment="10000.00", tenure=36)

    text = flat_text(pdf)
    reason = "is missing its specs (powertrain / engine capacity)"
    # Once in the TCO area, in place of the sections. (The Subscription row of the
    # pathways table above it says the same thing for its own reason, as before.)
    before_tco, tco_area = text.split("Total cost of ownership by pathway")
    assert tco_area.count(reason) == 1
    assert before_tco.count(reason) == 1 and "Not available:" in before_tco
    for section in ("60-month total cost of ownership", "Running costs a year", "Why this predicted value?",
                    "Risk alerts", "Contract return checklist"):
        assert section not in text


# --- Macan Electric RWD, 60 months, RM 57,500 down -----------------------------------------------


def test_the_electric_car_prints_its_alert_and_the_fallback_reason_instead_of_an_explanation(
    client, macan_electric, run10_model
):
    # Run 3 fix batch 6: on the recalibrated standard band (higher residuals) this car
    # no longer owes more than it is worth at any month, so there is no alert to print;
    # the high band (15,001 to 25,000 km a year) still crosses, from month 11
    # (re-derived independently; it was month 12 on the old standard band).
    pdf = export(client, macan_electric, downpayment="57500.00", band="high",
                 chart_svg=captured_chart("negative_equity_macan_ev_60.svg"))

    text = flat_text(pdf)
    assert "Risk alerts" in text
    assert "starting month 11" in text
    assert "you would owe more than the car is worth if sold at that point." in text
    assert "Why this predicted value?" in text
    assert "The machine-learning forecast does not cover electric cars yet: the training data has none." in text
    assert "New price" not in text  # no factor table for the estimated curve
    assert "Remaining loan vs. predicted car value" in text
    assert "60mo" in raw_text(pdf).splitlines()


# --- Run 2 fix batch 2 (E3, C6, E5): what the two resale figures are ---------------------------------------


RUN10_TYPICAL_ERROR_MAE = 0.1473  # run 10's log-linear MAE -> "typical error ≈ 16% of price" on the ML page

VIEWS_NOTE_BMW = (
    "At month 60, the lender's GFV residual for this car is RM 97,787.82 (36.79% of the price), while the predicted "
    "market value is RM 137,386.00 (51.7% of the price). The GFV figure is a guaranteed buy-back price that lenders "
    "set conservatively; the prediction is the expected market price, so the two are different things and can "
    "differ. Subscription fees are priced on the same conservative residual as GFV."
)
FORECAST_NOTE_BMW = (
    "Predicted resale value is a machine-learning estimate for this car's brand tier, age and mileage, scaled to "
    "this car's own price. Cars in the same brand tier share the same shape. Typical error is about 16% of the price."
)


def test_the_pdf_prints_both_notes_in_the_places_the_screen_does(client, bmw, run10_model):
    ProductionModel.objects.filter(pk=1).update(mae=RUN10_TYPICAL_ERROR_MAE)

    text = flat_text(export(client, bmw, chart_svg=captured_chart("negative_equity_bmw_60.svg")))

    assert VIEWS_NOTE_BMW in text and FORECAST_NOTE_BMW in text
    assert text.count(VIEWS_NOTE_BMW) == 1 and text.count(FORECAST_NOTE_BMW) == 1
    # views note: under the 60-month TCO table (after its equity note, before the running costs)
    assert text.index("60-month total cost of ownership") < text.index(VIEWS_NOTE_BMW) < text.index("Running costs a year")
    assert text.index("Net TCO credits your estimated equity at month 60") < text.index(VIEWS_NOTE_BMW)
    # forecast note: under "Why this predicted value?", after the factor table
    assert text.index("Why this predicted value?") < text.index("Predicted resale value RM 137,386.00") < text.index(
        FORECAST_NOTE_BMW)
    assert text.index(FORECAST_NOTE_BMW) < text.index("Contract return checklist")


def test_the_pdf_has_neither_note_for_the_electric_car(client, macan_electric, run10_model):
    ProductionModel.objects.filter(pk=1).update(mae=RUN10_TYPICAL_ERROR_MAE)

    text = flat_text(export(client, macan_electric, downpayment="57500.00",
                            chart_svg=captured_chart("negative_equity_macan_ev_60.svg")))

    assert "the lender's GFV residual for this car is" not in text
    assert "machine-learning estimate for this car's brand tier" not in text
    assert "The machine-learning forecast does not cover electric cars yet" in text  # its own message stays


def test_the_pdf_has_no_views_note_at_a_tenure_without_gfv_but_keeps_the_forecast_note(client, bmw, run10_model):
    ProductionModel.objects.filter(pk=1).update(mae=RUN10_TYPICAL_ERROR_MAE)

    text = flat_text(export(client, bmw, tenure=72))

    assert "the lender's GFV residual for this car is" not in text
    assert FORECAST_NOTE_BMW in text


def test_the_pdf_drops_the_error_sentence_when_the_metric_is_missing(client, bmw, run10_model):
    ProductionModel.objects.filter(pk=1).update(mae=None)

    text = flat_text(export(client, bmw))

    assert "Cars in the same brand tier share the same shape." in text
    assert "Typical error is about" not in text


def test_the_pdf_has_no_notes_without_a_serving_model(client, bmw):
    text = flat_text(export(client, bmw))  # no model deployed: the estimated curve

    assert "the lender's GFV residual for this car is" not in text
    assert "machine-learning estimate for this car's brand tier" not in text
    assert "RM 4,545.18" in text  # the rest of the TCO sections are unaffected
