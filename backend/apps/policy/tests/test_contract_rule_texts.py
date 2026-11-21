"""Run 1 fix batch 1, Step 4 and Step 6: stale ringgit fee amounts in contract
rule texts (refresh_contract_rule_texts + the guard on every write path), the
buyer's wording when a brand has no financing rate, and the residual basis
wording."""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from apps.audit.models import AuditActionCategory, AuditLog
from apps.policy.models import ContractPenaltyRule
from apps.policy.rule_text import (
    ESTIMATE_FOR_BRAND_CARS,
    RINGGIT_IN_TEXT_MESSAGE,
    model_name_candidates,
    model_names_in_text,
    reword_model_specific_estimate,
    strip_stale_fee_amounts,
    validate_no_ringgit_fee_amounts,
)
from apps.policy.serializers import ContractPenaltyRuleSerializer
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

# The real dev-database texts (shortened only where nothing changes).
BMW_TEXT = (
    "BMW Easy Drive (bmw.com.my): annual mileage is 20,000 or 25,000 km, and charges for excess mileage and "
    "vehicle condition are assessed by an independent appraiser when the car is returned. BMW Malaysia does not "
    "publish a per-km rate or an early-termination fee, so both figures here are ESTIMATES: RM0.50/km is the top "
    "of the only published Malaysian range (KINTO ONE), and the fee is 6 x this app's BMW 320i subscription fee "
    "(RM6,145), copying the KINTO rule. Confirm real figures with BMW Financial Services."
)
BMW_CLEAN = (
    "BMW Easy Drive (bmw.com.my): annual mileage is 20,000 or 25,000 km, and charges for excess mileage and "
    "vehicle condition are assessed by an independent appraiser when the car is returned. BMW Malaysia does not "
    "publish a per-km rate or an early-termination fee, so both figures here are ESTIMATES: RM0.50/km is the top "
    "of the only published Malaysian range (KINTO ONE). Confirm real figures with BMW Financial Services."
)
LEXUS_TEXT = (
    "Lexus KINTO ONE (published terms, kinto-my.com/faqs): the returned car is checked against KINTO's Fair Wear "
    "& Tear document and repair costs are charged depending on how severe the damage is. Excess mileage is "
    "RM0.20-0.50/km depending on model; RM0.50 (top of range) is used here for the ES 250. Early return costs 6 "
    "months' subscription fee or the remaining balance, whichever is lower; the fee shown is 6 x RM7,355.00 "
    "(ES 250 Luxury). All servicing must be done at authorised Lexus dealers."
)
LEXUS_CLEAN = (
    "Lexus KINTO ONE (published terms, kinto-my.com/faqs): the returned car is checked against KINTO's Fair Wear "
    "& Tear document and repair costs are charged depending on how severe the damage is. Excess mileage is "
    "RM0.20-0.50/km depending on model; RM0.50 (top of range) is used here for the ES 250. Early return costs 6 "
    "months' subscription fee or the remaining balance, whichever is lower. All servicing must be done at "
    "authorised Lexus dealers."
)


# --- the clean-up rule -------------------------------------------------------------------------


def test_the_stale_fee_clause_goes_and_the_citation_and_mileage_wording_stay():
    assert strip_stale_fee_amounts(BMW_TEXT) == BMW_CLEAN
    assert strip_stale_fee_amounts(LEXUS_TEXT) == LEXUS_CLEAN


def test_the_clean_up_is_idempotent_and_leaves_clean_text_byte_for_byte():
    assert strip_stale_fee_amounts(BMW_CLEAN) == BMW_CLEAN
    assert strip_stale_fee_amounts("QA test rule") == "QA test rule"  # no full stop added to untouched text


def test_a_per_km_rate_is_a_term_not_a_fee_and_is_kept():
    text = "Excess mileage is RM0.20-0.50/km; early return is charged per the rule."
    assert strip_stale_fee_amounts(text) == text


# --- run 1 fix batch 2: the widened guard --------------------------------------------------------------

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "live_contract_rule_texts.json").read_text(encoding="utf-8")
)
LIVE_TEXTS = _FIXTURE["texts"]
# The dev catalog's cars per brand, [name, trim] (run 2 fix batch 3).
LIVE_MODELS = _FIXTURE["models"]


@pytest.mark.parametrize("brand", sorted(LIVE_TEXTS))
def test_the_six_live_rule_texts_are_left_unchanged(brand):
    text = LIVE_TEXTS[brand]

    assert strip_stale_fee_amounts(text) == text
    validate_no_ringgit_fee_amounts(text)  # does not raise
    # Run 2 fix batch 3: the same texts also name no model (extends this guard, doesn't replace it).
    assert model_names_in_text(text, model_name_candidates(LIVE_MODELS.get(brand, []))) == []


@pytest.mark.parametrize("brand", sorted(LIVE_TEXTS))
def test_the_live_rule_texts_do_not_name_any_model_of_any_brand(brand):
    """A brand rule applies to every car of the brand - and a stray model name from another brand would be
    just as wrong, so the check runs against the whole catalog."""
    every_model = [pair for pairs in LIVE_MODELS.values() for pair in pairs]

    assert model_names_in_text(LIVE_TEXTS[brand], model_name_candidates(every_model)) == []


@pytest.mark.parametrize("text", [
    "Penalty of RM5,000 for returning the car.",
    "A charge of RM5,000 applies if you end the contract before term.",
    "Early exit costs MYR 5,000.",
    "Cancellation is charged at MYR5000.",
    "You pay 5,000 ringgit to terminate the contract.",
    "Penalties: RM1,200 if the car is returned with missing items.",
    "Excess mileage is RM0.50 per km, and early return costs RM5,000.",
])
def test_fee_amounts_without_the_old_fee_words_are_now_refused(text):
    with pytest.raises(ValidationError) as excinfo:
        validate_no_ringgit_fee_amounts(text)

    assert excinfo.value.messages == [RINGGIT_IN_TEXT_MESSAGE]


@pytest.mark.parametrize("text", [
    "Excess mileage is charged at RM0.50 per km.",
    "Excess mileage costs RM0.50 per-km.",
    "RM0.50 (top of range) is charged for every extra kilometre driven, per km over the cap.",
    "Excess mileage is charged at RM0.50 per kilometre.",
    "Excess mileage costs MYR 0.50/km.",
])
def test_per_km_rates_stay_allowed_however_they_are_written(text):
    assert strip_stale_fee_amounts(text) == text
    validate_no_ringgit_fee_amounts(text)


def test_a_damage_term_without_fee_wording_stays_allowed():
    # Chosen behaviour: a repair-cost term ("per panel") is not a fee for
    # leaving the contract, so it may stay in the text.
    text = "Wear beyond normal: RM300 per panel."

    assert strip_stale_fee_amounts(text) == text
    validate_no_ringgit_fee_amounts(text)


def test_mileage_figures_are_not_mistaken_for_ringgit():
    text = "Annual mileage is 20,000 or 25,000 km, and charges for excess mileage are assessed on return."

    assert strip_stale_fee_amounts(text) == text


# --- run 2 fix batch 3 (B7): a brand rule names no model ---------------------------------------------------

OLD_TOYOTA = (
    "Toyota KINTO ONE (published terms, kinto-my.com/faqs): the returned car is checked against KINTO's Fair Wear "
    "& Tear document and repair costs are charged depending on how severe the damage is. Excess mileage is "
    "RM0.20-0.50/km depending on model; RM0.50 (top of range) is used here for the Alphard. Early return costs 6 "
    "months' subscription fee or the remaining balance, whichever is lower. All servicing must be done at "
    "authorised Toyota dealers."
)
NEW_TOYOTA = OLD_TOYOTA.replace("is used here for the Alphard", "is used here as the estimate for this brand's cars")
OLD_LEXUS = LEXUS_CLEAN  # "... is used here for the ES 250. Early return costs ..." (the cleaned run 1 text)
NEW_LEXUS = OLD_LEXUS.replace("is used here for the ES 250", "is used here as the estimate for this brand's cars")


def test_the_guard_catches_the_old_texts_and_passes_the_new_ones():
    toyota_names = model_name_candidates(LIVE_MODELS["Toyota"])
    lexus_names = model_name_candidates(LIVE_MODELS["Lexus"])

    assert model_names_in_text(OLD_TOYOTA, toyota_names) == ["Alphard"]
    assert model_names_in_text(OLD_LEXUS, lexus_names) == ["ES", "ES 250"]
    assert model_names_in_text(NEW_TOYOTA, toyota_names) == []
    assert model_names_in_text(NEW_LEXUS, lexus_names) == []
    assert NEW_TOYOTA == LIVE_TEXTS["Toyota"] and NEW_LEXUS == LIVE_TEXTS["Lexus"]


def test_a_model_name_is_matched_as_a_whole_word_only():
    names = model_name_candidates([("ES", "250 Luxury")])

    assert model_names_in_text("Licences, yes and EXPRESS are not the ES.", names) == ["ES"]
    assert model_names_in_text("Licences, yes and EXPRESS only.", names) == []


def test_the_reword_changes_only_the_model_sentence_and_only_for_a_real_model():
    names = model_name_candidates([("Alphard", "2.4 Executive Lounge")])

    assert reword_model_specific_estimate(OLD_TOYOTA, names) == NEW_TOYOTA
    # idempotent
    assert reword_model_specific_estimate(NEW_TOYOTA, names) == NEW_TOYOTA
    # "used here for the" followed by something that is not one of the brand's models stays as written
    text = "RM0.50 (top of range) is used here for the standard fleet."
    assert reword_model_specific_estimate(text, names) == text
    # and a brand with no models on file can't be told what to reword
    assert reword_model_specific_estimate(OLD_TOYOTA, []) == OLD_TOYOTA
    assert ESTIMATE_FOR_BRAND_CARS in NEW_TOYOTA


@pytest.fixture
def named_rules(create_user):
    create_user(email="admin@flexidrivemy.local", role="admin")
    toyota = Brand.objects.create(name="Toyota", tier_code="1")
    lexus = Brand.objects.create(name="Lexus", tier_code="1")
    VehicleModel.objects.create(
        brand=toyota, name="Alphard", trim="2.4 Executive Lounge", body_segment=BodySegment.MPV, msrp="548000.00",
        engine_capacity_kw="201.53", powertrain="petrol", engine_capacity_cc=2393,
    )
    VehicleModel.objects.create(
        brand=lexus, name="ES", trim="250 Luxury", body_segment=BodySegment.SEDAN, msrp="356888.00",
        engine_capacity_kw="151.00", powertrain="petrol", engine_capacity_cc=2487,
    )
    ContractPenaltyRule.objects.bulk_create([
        ContractPenaltyRule(brand=toyota, excess_mileage_charge_per_km="0.50", wear_tear_tolerance_description=OLD_TOYOTA),
        ContractPenaltyRule(brand=lexus, excess_mileage_charge_per_km="0.50", wear_tear_tolerance_description=OLD_LEXUS),
    ])
    return {"toyota": toyota, "lexus": lexus}


def test_the_dry_run_shows_the_reworded_sentence_and_writes_nothing(named_rules):
    before = state()

    output = run()

    assert state() == before
    assert "AFTER:  " + NEW_TOYOTA in output and "AFTER:  " + NEW_LEXUS in output
    assert "2 to change" in output


def test_apply_rewords_both_with_audit_rows_and_a_second_run_changes_nothing(named_rules):
    existing = [row["id"] for row in AuditLog.objects.values("id")]

    output = run("--apply", "--actor", "admin@flexidrivemy.local")

    assert "Done: 2 rule(s) updated." in output
    assert ContractPenaltyRule.objects.get(brand=named_rules["toyota"]).wear_tear_tolerance_description == NEW_TOYOTA
    assert ContractPenaltyRule.objects.get(brand=named_rules["lexus"]).wear_tear_tolerance_description == NEW_LEXUS
    new_rows = AuditLog.objects.exclude(pk__in=existing)
    assert new_rows.count() == 2
    assert {row.action for row in new_rows} == {AuditActionCategory.UPDATE}
    assert {row.actor_email for row in new_rows} == {"admin@flexidrivemy.local"}
    toyota_row = new_rows.get(resource_id=str(ContractPenaltyRule.objects.get(brand=named_rules["toyota"]).pk))
    assert toyota_row.before_data["wear_tear_tolerance_description"] == OLD_TOYOTA
    assert toyota_row.after_data["wear_tear_tolerance_description"] == NEW_TOYOTA
    assert "no model named" in toyota_row.after_data["correction"]
    after_first = state()

    again = run("--apply", "--actor", "admin@flexidrivemy.local")

    assert state() == after_first
    assert "0 to change" in again and "Nothing to change." in again


def test_after_the_refresh_no_active_brand_rule_names_a_model_of_its_brand(named_rules):
    run("--apply", "--actor", "admin@flexidrivemy.local")

    for rule in ContractPenaltyRule.objects.filter(is_active=True, brand__isnull=False).select_related("brand"):
        models = VehicleModel.objects.filter(brand=rule.brand).values_list("name", "trim")
        assert model_names_in_text(rule.wear_tear_tolerance_description, model_name_candidates(models)) == []


def test_one_rule_that_needs_both_fixes_gets_one_audit_row_naming_both(create_user):
    create_user(email="admin@flexidrivemy.local", role="admin")
    lexus = Brand.objects.create(name="Lexus", tier_code="1")
    VehicleModel.objects.create(
        brand=lexus, name="ES", trim="250 Luxury", body_segment=BodySegment.SEDAN, msrp="356888.00",
        engine_capacity_kw="151.00", powertrain="petrol", engine_capacity_cc=2487,
    )
    ContractPenaltyRule.objects.bulk_create([
        ContractPenaltyRule(brand=lexus, excess_mileage_charge_per_km="0.50", wear_tear_tolerance_description=LEXUS_TEXT),
    ])

    run("--apply", "--actor", "admin@flexidrivemy.local")

    assert ContractPenaltyRule.objects.get(brand=lexus).wear_tear_tolerance_description == NEW_LEXUS
    row = AuditLog.objects.filter(resource_type="policy.ContractPenaltyRule").latest("id")
    assert "run 1 fix batch 1" in row.after_data["correction"] and "no model named" in row.after_data["correction"]


# --- refresh_contract_rule_texts -------------------------------------------------------------------


@pytest.fixture
def rules(create_user):
    create_user(email="admin@flexidrivemy.local", role="admin")
    bmw = Brand.objects.create(name="BMW", tier_code="2")
    lexus = Brand.objects.create(name="Lexus", tier_code="1")
    clean_brand = Brand.objects.create(name="CleanBrand", tier_code="3")
    # Written straight to the table, as the old rows were (the guard below
    # now refuses them on every write path).
    ContractPenaltyRule.objects.bulk_create([
        ContractPenaltyRule(brand=bmw, excess_mileage_charge_per_km="0.50", wear_tear_tolerance_description=BMW_TEXT),
        ContractPenaltyRule(brand=lexus, excess_mileage_charge_per_km="0.50", wear_tear_tolerance_description=LEXUS_TEXT),
        ContractPenaltyRule(brand=clean_brand, excess_mileage_charge_per_km="0.50", wear_tear_tolerance_description="Clean."),
    ])
    archived = Brand.objects.create(name="ArchivedBrand", tier_code="3")
    ContractPenaltyRule.objects.bulk_create([
        ContractPenaltyRule(brand=archived, excess_mileage_charge_per_km="0.50", is_active=False,
                            wear_tear_tolerance_description="Old fee is RM9,999 for early return."),
    ])
    return {"bmw": bmw, "lexus": lexus}


def run(*args):
    out = StringIO()
    call_command("refresh_contract_rule_texts", *args, stdout=out)
    return out.getvalue()


def state():
    return {"rules": list(ContractPenaltyRule.objects.order_by("pk").values()), "audit": AuditLog.objects.count()}


def test_the_dry_run_lists_each_change_before_and_after_and_writes_nothing(rules):
    before = state()

    output = run()

    assert state() == before
    assert output.startswith("DRY RUN - nothing will be changed")
    assert "BEFORE: " + BMW_TEXT in output and "AFTER:  " + BMW_CLEAN in output
    assert "AFTER:  " + LEXUS_CLEAN in output
    assert "2 to change; 2 already clean; 4 active rule(s) in total" in output  # + the seeded default rule
    assert "Dry run only. Re-run with --apply" in output


def test_apply_rewrites_the_texts_and_writes_one_audit_row_each(rules):
    existing = list(AuditLog.objects.values())

    output = run("--apply", "--actor", "admin@flexidrivemy.local")

    assert "Done: 2 rule(s) updated." in output
    assert ContractPenaltyRule.objects.get(brand=rules["bmw"]).wear_tear_tolerance_description == BMW_CLEAN
    assert ContractPenaltyRule.objects.get(brand=rules["lexus"]).wear_tear_tolerance_description == LEXUS_CLEAN
    new_rows = AuditLog.objects.exclude(pk__in=[row["id"] for row in existing])
    assert new_rows.count() == 2
    assert {row.action for row in new_rows} == {AuditActionCategory.UPDATE}
    assert {row.resource_type for row in new_rows} == {"policy.ContractPenaltyRule"}
    assert {row.actor_email for row in new_rows} == {"admin@flexidrivemy.local"}
    bmw_row = new_rows.get(resource_id=str(ContractPenaltyRule.objects.get(brand=rules["bmw"]).pk))
    assert bmw_row.before_data["wear_tear_tolerance_description"] == BMW_TEXT
    assert bmw_row.after_data["wear_tear_tolerance_description"] == BMW_CLEAN
    assert list(AuditLog.objects.filter(pk__in=[row["id"] for row in existing]).values()) == existing
    # an archived rule is never touched
    assert "RM9,999" in ContractPenaltyRule.objects.get(brand__name="ArchivedBrand").wear_tear_tolerance_description


def test_a_second_run_changes_nothing(rules):
    run("--apply", "--actor", "admin@flexidrivemy.local")
    after_first = state()

    output = run("--apply", "--actor", "admin@flexidrivemy.local")

    assert state() == after_first
    assert "0 to change" in output and "Nothing to change." in output


def test_the_dry_run_over_the_six_live_texts_has_nothing_to_change():
    ContractPenaltyRule.objects.filter(brand__isnull=True).update(wear_tear_tolerance_description=LIVE_TEXTS["default"])
    ContractPenaltyRule.objects.bulk_create([
        ContractPenaltyRule(
            brand=Brand.objects.create(name=name, tier_code="2"), excess_mileage_charge_per_km="0.50",
            wear_tear_tolerance_description=text,
        )
        for name, text in LIVE_TEXTS.items() if name != "default"
    ])

    output = run()

    assert "0 to change; 6 already clean; 6 active rule(s) in total" in output


def test_an_unknown_actor_is_refused_before_anything_is_written(rules):
    before = state()

    with pytest.raises(CommandError):
        run("--apply", "--actor", "nobody@example.com")

    assert state() == before


# --- the guard on every write path -----------------------------------------------------------------


def test_the_api_serializer_refuses_a_typed_fee_amount():
    brand = Brand.objects.create(name="GuardBrand", tier_code="2")
    serializer = ContractPenaltyRuleSerializer(data={
        "brand": brand.id, "excess_mileage_charge_per_km": "0.50", "early_termination_months": "6",
        "wear_tear_tolerance_description": "The fee is 6 x the subscription fee (RM6,145).",
    })

    assert not serializer.is_valid()
    assert serializer.errors["wear_tear_tolerance_description"] == [RINGGIT_IN_TEXT_MESSAGE]


def test_the_api_endpoint_refuses_it_too(admin_user):
    brand = Brand.objects.create(name="GuardBrand2", tier_code="2")
    client = APIClient()
    client.force_authenticate(user=admin_user)

    response = client.post("/api/policy/contract-penalty-rules/", {
        "brand": brand.id, "excess_mileage_charge_per_km": "0.50", "early_termination_months": "6",
        "wear_tear_tolerance_description": "Early return fee shown is 6 x RM7,355.00.",
    }, format="json")

    assert response.status_code == 400
    assert response.data["wear_tear_tolerance_description"] == [RINGGIT_IN_TEXT_MESSAGE]


def test_the_django_admin_form_refuses_it(rf, admin_user):
    brand = Brand.objects.create(name="GuardBrand3", tier_code="2")
    model_admin = site._registry[ContractPenaltyRule]
    request = rf.get("/admin/policy/contractpenaltyrule/add/")
    request.user = admin_user
    form_class = model_admin.get_form(request)

    form = form_class(data={
        "brand": brand.id, "excess_mileage_charge_per_km": "0.50", "early_termination_months": "6",
        "wear_tear_tolerance_description": "The fee is RM6,145 for early termination.", "source_note": "",
        "is_active": True,
    })

    assert not form.is_valid()
    assert form.errors["wear_tear_tolerance_description"] == [RINGGIT_IN_TEXT_MESSAGE]


def test_the_cleaned_texts_and_a_per_km_rate_are_still_accepted():
    brand = Brand.objects.create(name="GuardBrand4", tier_code="2")
    serializer = ContractPenaltyRuleSerializer(data={
        "brand": brand.id, "excess_mileage_charge_per_km": "0.50", "early_termination_months": "6",
        "wear_tear_tolerance_description": LEXUS_CLEAN,
    })

    assert serializer.is_valid(), serializer.errors


# --- Step 6: plain words for buyers --------------------------------------------------------------------


def test_a_buyer_is_told_plainly_and_vehicle_readiness_keeps_the_technical_reason():
    from apps.comparisons.services import RATE_NOT_SET_MESSAGE, ComparisonConfigError, get_active_interest_rate

    brand = Brand.objects.create(name="NoRateBrand", tier_code="2")

    with pytest.raises(ComparisonConfigError) as excinfo:
        get_active_interest_rate(brand)

    assert str(excinfo.value) == RATE_NOT_SET_MESSAGE == (
        "Hire Purchase and GFV aren't available for this car yet because its financing rate hasn't been set up."
    )
    assert excinfo.value.admin_message == "No active interest rate configured for brand 'NoRateBrand'."


def test_the_tco_400_uses_the_buyers_wording(regular_user):
    from apps.vehicles.models import BodySegment, VehicleModel

    brand = Brand.objects.create(name="NoRateBrand2", tier_code="2")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="M", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00",
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    client = APIClient()
    client.force_authenticate(user=regular_user)

    response = client.get("/api/depreciation/tco/", {
        "vehicle": vehicle.id, "tenure_months": 36, "mileage_band": "standard", "downpayment": "30000.00",
    })

    assert response.status_code == 400
    assert response.data["detail"] == (
        "Hire Purchase and GFV aren't available for this car yet because its financing rate hasn't been set up."
    )
    assert "configured" not in response.data["detail"]


def test_the_residual_basis_says_points_and_a_readable_powertrain():
    import importlib

    from django.apps import apps as django_apps

    from apps.policy.residuals import resolve_residual_ratio
    from apps.vehicles.models import BodySegment, VehicleModel

    brand = Brand.objects.create(name="Porsche", tier_code="1")
    importlib.import_module(
        "apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule"
    ).seed_brand_adjustments(django_apps)
    ev = VehicleModel.objects.create(
        brand=brand, name="Macan Electric", trim="RWD", body_segment=BodySegment.SUV, msrp="575000.00",
        engine_capacity_kw="261.10", powertrain="bev",
    )
    phev = VehicleModel.objects.create(
        brand=brand, name="Cayenne", trim="E-Hybrid", body_segment=BodySegment.SUV, msrp="700000.00",
        engine_capacity_kw="346.00", powertrain="phev", engine_capacity_cc=2995,
    )

    assert resolve_residual_ratio(ev, 36, "standard").basis == (
        "Estimate: 51.79% baseline for 36 months / standard mileage, +5 points Porsche, -8 points electric"
    )
    assert resolve_residual_ratio(phev, 36, "standard").basis.endswith("-3 points plug-in hybrid")
    assert " pts " not in resolve_residual_ratio(ev, 48, "high").basis
