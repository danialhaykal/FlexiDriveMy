"""Run 2 fix batch 1: the TCO tab's remaining sections, formatted server-side for
the PDF (apps/exports/comparison_rows.py), plus the Malaysia-time stamp and the
2-decimal flat rate. Pure formatting of the server's own figures - nothing here
computes money."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.utils.html import escape

from apps.exports import comparison_rows as rows
from apps.exports.rendering import build_report_html

D = Decimal


def report(**overrides):
    base = {
        "model_degraded": False,
        "degraded_reason": None,
        "hp_monthly": D("4545.18"),
        "tco_gross": D("338397.80"),
        "tco_net": D("203742.51"),
        "road_tax_annual": D("379.00"),
        "insurance_annual": D("4784.40"),
        "maintenance_annual": D("2658.00"),
        "ncd_percent": D("0.00"),
        "operating_cost_basis": {
            "road_tax": "1,998 cc petrol, saloon - JPJ cc schedule",
            "insurance": "1.8% of RM 265,800.00",
            "maintenance": "1.0% of price (floor RM 1,200)",
        },
        "resale_value_explanation": {
            "base_value": 265800.0,
            "contributions": {
                "vehicle_age": -107914.0312, "mileage": -23230.6788, "brand_code": 0.0,
                "engine_litres": 0.0, "body_type": 0.0, "recond": 0.0,
            },
            "predicted_value": 134655.29,
        },
        "risk_alerts": [],
        "contract_checklist": {
            "excess_mileage_charge_per_km": D("0.50"),
            "early_settlement": {
                "method": "reducing_balance", "after_12_months": D("196280.44"), "at_half_term": D("127476.28"),
                "half_term_month": 30, "penalty": "none",
            },
            "subscription_early_return_months": D("3.00"),
            "subscription_early_return_fee": None,
            "early_termination_months": D("3.00"),
            "wear_tear_tolerance_description": "Normal wear is accepted.",
            "rule_source": "default",
            "early_termination_months_source": "default",
        },
    }
    base.update(overrides)
    return base


# --- Malaysia time and the flat rate ---------------------------------------------------------


@pytest.mark.parametrize(
    "utc, shown",
    [
        (datetime(2026, 10, 19, 5, 13, tzinfo=timezone.utc), "19 October 2026, 13:13 MYT"),  # the bug: 05:13 printed
        (datetime(2026, 12, 31, 17, 0, tzinfo=timezone.utc), "01 January 2027, 01:00 MYT"),  # crosses midnight
        (datetime(2026, 3, 1, 15, 59, tzinfo=timezone.utc), "01 March 2026, 23:59 MYT"),
    ],
)
def test_generated_on_is_malaysia_time(utc, shown):
    assert rows.format_generated_at(utc) == shown


@pytest.mark.django_db  # the mileage-band label reads the policy tables
def test_the_export_context_stamps_malaysia_time(monkeypatch):
    monkeypatch.setattr(rows.timezone, "now", lambda: datetime(2026, 10, 19, 5, 13, tzinfo=timezone.utc))
    comparison = {"tenure_months": 60, "downpayment": D("26580.00"), "mileage_band": "standard",
                  "hire_purchase": None, "gfv_leasing": None, "subscription": None,
                  "unavailable": {"hire_purchase": "x", "gfv_leasing": "x", "subscription": "x"}}

    assert rows.build_export_context(comparison)["generated_at"] == "19 October 2026, 13:13 MYT"


@pytest.mark.parametrize("stored, shown", [("2.8000", "2.80%"), ("2.8050", "2.81%"), ("2.8049", "2.80%"),
                                           ("3.5000", "3.50%"), ("10", "10.00%")])
def test_the_flat_rate_prints_with_two_decimals_half_up(stored, shown):
    assert rows._format_flat_rate(D(stored)) == shown


# --- 60-month summary and running costs -------------------------------------------------------------


def test_summary_and_running_costs_carry_the_screens_wording():
    sections = rows.build_tco_sections(report())

    assert sections["summary"] == {
        "hp_monthly": "RM 4,545.18", "tco_gross": "RM 338,397.80", "tco_net": "RM 203,742.51",
        "equity_note": rows.EQUITY_NOTE,
    }
    assert "Net TCO credits your estimated equity at month 60" in rows.EQUITY_NOTE
    costs = sections["running_costs"]
    assert [(i["label"], i["amount"], i["basis"]) for i in costs["items"]] == [
        ("Road tax", "RM 379.00 / yr", "1,998 cc petrol, saloon - JPJ cc schedule"),
        ("Insurance", "RM 4,784.40 / yr", "1.8% of RM 265,800.00"),
        ("Maintenance", "RM 2,658.00 / yr", "1.0% of price (floor RM 1,200)"),
    ]
    assert costs["assumption_note"] == (
        "Estimates for Peninsular Malaysia, private car; insurance and maintenance are planning assumptions, "
        "not quotes."
    )


def test_the_before_ncd_note_is_only_for_a_buyer_with_no_discount():
    assert rows.build_tco_sections(report())["running_costs"]["ncd_note"] == (
        "Insurance shown before No-Claim Discount. Add your NCD in Financial Profile."
    )
    with_ncd = report(ncd_percent=D("55.00"))
    with_ncd["operating_cost_basis"]["insurance"] = "1.8% of RM 265,800.00, less 55% NCD"
    sections = rows.build_tco_sections(with_ncd)
    assert sections["running_costs"]["ncd_note"] is None
    assert sections["running_costs"]["items"][1]["basis"].endswith("less 55% NCD")  # the basis says it


# --- "Why this predicted value?" -------------------------------------------------------------------


def test_the_explanation_lists_the_moving_factors_rounded_to_two_places_and_hides_exact_zeros():
    section = rows.build_tco_sections(report())["explanation"]

    assert section["new_price"] == "RM 265,800.00"
    assert section["predicted"] == "RM 134,655.29"
    assert section["rows"] == [
        {"label": "Age", "value": "-RM 107,914.03"},
        {"label": "Mileage", "value": "-RM 23,230.68"},
    ]
    assert section["help"] == (
        "How much each factor moved the value from the new price (worked out on a log scale and shared in proportion)."
    )


def test_a_factor_that_rounds_to_zero_is_hidden_and_half_a_cent_is_not():
    contributions = {"vehicle_age": -1000.0, "mileage": 0.004, "brand_code": -0.004, "engine_litres": 0.005,
                     "body_type": -0.005, "recond": 2000.0}
    section = rows.build_tco_sections(
        report(resale_value_explanation={"base_value": 100000.0, "contributions": contributions,
                                         "predicted_value": 101000.0})
    )["explanation"]

    assert section["rows"] == [
        {"label": "Age", "value": "-RM 1,000.00"},
        {"label": "Engine size", "value": "+RM 0.01"},
        {"label": "Body type", "value": "-RM 0.01"},
        {"label": "Recond import", "value": "+RM 2,000.00"},
    ]


def test_the_estimated_curve_prints_its_reason_instead_of_an_explanation():
    reason = ("Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast "
              "does not cover electric cars yet: the training data has none.")

    section = rows.build_tco_sections(
        report(model_degraded=True, degraded_reason=reason, resale_value_explanation=None)
    )["explanation"]

    assert section == {"fallback_reason": reason}


def test_no_explanation_and_no_fallback_means_no_section():
    assert rows.build_tco_sections(report(resale_value_explanation=None))["explanation"] is None


# --- risk alerts and the checklist ----------------------------------------------------------------------


def test_every_risk_alert_message_is_carried():
    alerts = [
        {"code": "negative_equity_within_horizon", "severity": "warning", "message": "falls below ... starting month 12"},
        {"code": "declared_mileage_mismatch", "severity": "info", "message": "Your declared band differs."},
    ]

    sections = rows.build_tco_sections(report(risk_alerts=alerts))

    assert sections["risk_alerts"] == [
        {"severity": "warning", "message": "falls below ... starting month 12"},
        {"severity": "info", "message": "Your declared band differs."},
    ]


def test_the_checklist_rows_match_the_screens_wording():
    checklist = rows.build_tco_sections(report())["checklist"]

    assert checklist["rows"] == [
        {"label": "Excess mileage charge", "value": "RM 0.50 / km"},
        {"label": "Settling a Hire Purchase loan early",
         "value": "No penalty under the reducing-balance method. Estimated amount to settle after 12 months: "
                  "RM 196,280.44; at month 30: RM 127,476.28."},
        {"label": "Returning a subscription car early", "value": "Up to 3 months of the subscription fee."},
        {"label": "Wear & tear tolerance", "value": "Normal wear is accepted."},
    ]
    assert checklist["source_note"] == (
        "Terms from the default contract rule - planning estimates; typical terms vary by provider."
    )


def test_a_short_loan_has_no_after_12_months_figure_and_a_fee_is_shown_when_there_is_one():
    data = report()
    data["contract_checklist"]["early_settlement"].update(after_12_months=None, at_half_term=D("20000.00"),
                                                          half_term_month=6)
    data["contract_checklist"].update(subscription_early_return_fee=D("17105.79"),
                                      subscription_early_return_months=D("1.00"))

    checklist = rows.build_tco_sections(data)["checklist"]

    assert checklist["rows"][1]["value"] == (
        "No penalty under the reducing-balance method. Estimated amount to settle at month 6: RM 20,000.00."
    )
    assert checklist["rows"][2]["value"] == (
        "Up to 1 month of the subscription fee (about RM 17,105.79), or the fees left, whichever is lower."
    )


def test_a_brand_rule_that_inherits_the_default_months_says_so():
    data = report()
    data["contract_checklist"].update(rule_source="brand", early_termination_months_source="default")
    assert rows.build_tco_sections(data)["checklist"]["source_note"] == (
        "Terms from this brand's own contract rule (subscription early-return months from the default rule)."
    )
    data["contract_checklist"]["early_termination_months_source"] = "brand"
    assert rows.build_tco_sections(data)["checklist"]["source_note"] == "Terms from this brand's own contract rule."


def test_a_brand_with_no_rule_has_no_checklist_and_the_pdf_says_so():
    sections = rows.build_tco_sections(report(contract_checklist=None))
    assert sections["checklist"] is None

    html = build_report_html(
        vehicle_label="X", pathways=[], tenure_months=60, downpayment="RM 1.00", mileage_band_label="Standard",
        generated_at="now", tco_sections=sections,
    )
    assert "Contract terms not yet configured for this brand" in html


def test_the_sections_are_plain_strings_so_they_survive_the_task_boundary():
    import json

    sections = rows.build_tco_sections(report())

    assert json.loads(json.dumps(sections)) == sections


# --- rendering ----------------------------------------------------------------------------------------------


def test_the_html_has_the_sections_only_when_the_tco_was_built():
    context = dict(vehicle_label="X", pathways=[], tenure_months=60, downpayment="RM 1.00",
                   mileage_band_label="Standard", generated_at="now")

    with_sections = build_report_html(**context, tco_sections=rows.build_tco_sections(report()))
    without = build_report_html(**context, tco_unavailable_reason="This car has no specs.")
    legacy = build_report_html(**context)  # a task queued before this batch passes none of the new keys

    for heading in ("60-month total cost of ownership", "Running costs a year", "Why this predicted value?",
                    "Contract return checklist"):
        assert heading in with_sections
        assert heading not in without and heading not in legacy
    assert "This car has no specs." in without
    assert "Risk alerts" not in with_sections  # none to print


# --- Run 2 fix batch 2 (E3, C6, E5): the two resale notes in the PDF sections ----------------------------------

VIEWS = "At month 60, the lender's GFV residual for this car is RM 93,030.00 (35% of the price), while ..."
FORECAST = "Predicted resale value is a machine-learning estimate for this car's brand tier ... about 16% of the price."


def test_the_views_note_goes_into_the_summary_only_when_the_report_has_one():
    assert rows.build_tco_sections(report(resale_views_note=VIEWS))["summary"]["resale_views_note"] == VIEWS
    for absent in ({}, {"resale_views_note": None}, {"resale_views_note": ""}):
        assert "resale_views_note" not in rows.build_tco_sections(report(**absent))["summary"]


def test_the_forecast_note_goes_under_the_explanation_only_when_there_is_one():
    assert rows.build_tco_sections(report(resale_forecast_note=FORECAST))["explanation"]["forecast_note"] == FORECAST
    for absent in ({}, {"resale_forecast_note": None}, {"resale_forecast_note": ""}):
        assert "forecast_note" not in rows.build_tco_sections(report(**absent))["explanation"]


def test_the_forecast_note_is_not_printed_on_the_estimated_curve_even_if_a_report_carried_one():
    sections = rows.build_tco_sections(report(
        model_degraded=True, degraded_reason="Estimated curve.", resale_value_explanation=None,
        resale_forecast_note=FORECAST,
    ))

    assert sections["explanation"] == {"fallback_reason": "Estimated curve."}


def test_the_html_prints_the_notes_where_expected_and_nothing_when_they_are_absent():
    context = dict(vehicle_label="X", pathways=[], tenure_months=60, downpayment="RM 1.00",
                   mileage_band_label="Standard", generated_at="now")

    with_notes = build_report_html(
        **context, tco_sections=rows.build_tco_sections(report(resale_views_note=VIEWS, resale_forecast_note=FORECAST)))
    without = build_report_html(**context, tco_sections=rows.build_tco_sections(report()))

    # The template autoescapes (the apostrophe in "lender's" becomes &#x27;), as for every other text in it.
    views, forecast = escape(VIEWS), escape(FORECAST)
    assert with_notes.count(views) == 1 and with_notes.count(forecast) == 1
    assert with_notes.index("60-month total cost of ownership") < with_notes.index(views) < with_notes.index("Running costs a year")
    assert with_notes.index("Why this predicted value?") < with_notes.index(forecast)
    assert views not in without and forecast not in without
