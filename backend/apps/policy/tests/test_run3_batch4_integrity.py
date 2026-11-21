"""Run 3 fix batch 4, item 7 - the data-integrity S3s:

  F-11  Default Priority Weights must add up to exactly 1.0000 (4 dp)
  F-13  a provider quote may only be filed under an active car
  F-15  the early-return fee months may not exceed the longest subscription
        (read from the active SubscriptionPolicy row)
  F-16  a brand's wear-and-tear text may not name one of that brand's models
  F-12  no future-dated effective_from on any policy table (admin forms + serializers)

Each is checked on the API and on the Django admin form where the table is edited there.
"""

import datetime
import json
from pathlib import Path

import pytest
from django.contrib.admin.sites import site
from django.utils import timezone
from rest_framework.test import APIClient

from apps.policy.effective_dates import FUTURE_EFFECTIVE_FROM_MESSAGE
from apps.policy.models import (
    ContractPenaltyRule,
    EvRoadTaxGroup,
    MCDACriteriaWeight,
    MCDACriterion,
    OperatingCostRate,
    ResidualAdjustment,
    ResidualBaseline,
    RoadTaxCcBand,
    SubscriptionPlan,
    SubscriptionPolicy,
)
from apps.policy.rule_text import model_name_candidates, model_name_in_text_message
from apps.policy.serializers import (
    ARCHIVED_VEHICLE_MESSAGE,
    EvRoadTaxGroupReadSerializer,
    OperatingCostRateReadSerializer,
    ResidualAdjustmentReadSerializer,
    ResidualBaselineReadSerializer,
    RoadTaxCcBandReadSerializer,
    SubscriptionPolicyReadSerializer,
)
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def admin_form(model, rf, user, instance=None):
    model_admin = site._registry[model]
    request = rf.get("/admin/")
    request.user = user
    return model_admin.get_form(request, obj=instance)


# --- F-11 -----------------------------------------------------------------------------------------------------------


def put_weights(client, a, b, c):
    return client.put("/api/policy/mcda-weights/", {"weights": [
        {"criterion": MCDACriterion.UPFRONT_CASH_PRESERVATION, "default_weight": a},
        {"criterion": MCDACriterion.MAINTENANCE_PROTECTION, "default_weight": b},
        {"criterion": MCDACriterion.OWNERSHIP_EQUITY, "default_weight": c},
    ]}, format="json")


@pytest.mark.parametrize("weights, total", [
    (("0.3333", "0.3333", "0.3333"), "0.9999"),
    (("0.3334", "0.3333", "0.3334"), "1.0001"),
])
def test_weights_a_hair_off_one_are_refused_with_the_same_message(admin_client, weights, total):
    before = list(MCDACriteriaWeight.objects.order_by("criterion").values_list("default_weight", flat=True))

    response = put_weights(admin_client, *weights)

    assert response.status_code == 400
    assert response.data["weights"] == [f"Weights must sum to 1.0 (got {total})."]
    assert list(MCDACriteriaWeight.objects.order_by("criterion").values_list("default_weight", flat=True)) == before


def test_weights_that_add_up_to_exactly_one_are_accepted(admin_client):
    assert put_weights(admin_client, "0.3333", "0.3333", "0.3334").status_code == 200
    assert put_weights(admin_client, "0.3400", "0.3300", "0.3300").status_code == 200  # the seeded defaults


# --- F-13 -----------------------------------------------------------------------------------------------------------


@pytest.fixture
def brand():
    return Brand.objects.create(name="IntegrityBrand", tier_code="2")


def make_car(brand, name="Saloon", trim="2.0 Luxury", is_active=True):
    return VehicleModel.objects.create(
        brand=brand, name=name, trim=trim, body_segment=BodySegment.SEDAN, msrp="300000.00",
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998, is_active=is_active,
    )


def test_a_quote_for_an_archived_car_is_refused(admin_client, brand):
    archived = make_car(brand, is_active=False)

    response = admin_client.post("/api/policy/subscription-plans/", {"vehicle": archived.pk, "fee_monthly": "2500.00"},
                                 format="json")

    assert response.status_code == 400
    assert response.data["vehicle"] == [ARCHIVED_VEHICLE_MESSAGE]
    assert ARCHIVED_VEHICLE_MESSAGE == "Vehicle is archived and cannot be assigned to new records."
    assert not SubscriptionPlan.objects.filter(vehicle=archived).exists()


def test_a_quote_for_an_active_car_is_accepted(admin_client, brand):
    car = make_car(brand)

    response = admin_client.post("/api/policy/subscription-plans/", {"vehicle": car.pk, "fee_monthly": "2500.00"},
                                 format="json")

    assert response.status_code == 201, response.data


def test_an_existing_quote_on_a_car_archived_later_can_still_be_edited(admin_client, brand):
    car = make_car(brand)
    plan = SubscriptionPlan.objects.create(vehicle=car, fee_monthly="2500.00")
    VehicleModel.objects.filter(pk=car.pk).update(is_active=False)

    response = admin_client.patch(f"/api/policy/subscription-plans/{plan.pk}/",
                                  {"vehicle": car.pk, "fee_monthly": "2600.00"}, format="json")

    assert response.status_code == 200, response.data


def test_moving_a_quote_to_another_archived_car_is_refused(admin_client, brand):
    plan = SubscriptionPlan.objects.create(vehicle=make_car(brand), fee_monthly="2500.00")
    archived = make_car(brand, name="Other", is_active=False)

    response = admin_client.patch(f"/api/policy/subscription-plans/{plan.pk}/", {"vehicle": archived.pk},
                                  format="json")

    assert response.status_code == 400
    assert response.data["vehicle"] == [ARCHIVED_VEHICLE_MESSAGE]


# --- F-15 -----------------------------------------------------------------------------------------------------------


def rule_payload(brand, **overrides):
    payload = {
        "brand": brand.pk if brand is not None else None, "excess_mileage_charge_per_km": "0.50",
        "early_termination_months": "3.00", "wear_tear_tolerance_description": "Normal wear is accepted.",
    }
    payload.update(overrides)
    return payload


def active_policy_max():
    return SubscriptionPolicy.objects.get(is_active=True).max_tenure_months


def test_the_seeded_policy_is_the_one_read():
    assert active_policy_max() == 36


def test_more_months_than_the_longest_subscription_are_refused(admin_client, brand):
    response = admin_client.post("/api/policy/contract-penalty-rules/",
                                 rule_payload(brand, early_termination_months="60.00"), format="json")

    assert response.status_code == 400
    assert response.data["early_termination_months"] == [
        "The early-return fee can't be more than 36 months of fee - the longest subscription plan is 36 months."
    ]


def test_exactly_the_longest_subscription_is_accepted(admin_client, brand):
    response = admin_client.post("/api/policy/contract-penalty-rules/",
                                 rule_payload(brand, early_termination_months="36.00"), format="json")

    assert response.status_code == 201, response.data


def test_the_cap_follows_the_policy_row_not_a_fixed_36(admin_client, brand):
    SubscriptionPolicy.objects.filter(is_active=True).update(max_tenure_months=24)

    refused = admin_client.post("/api/policy/contract-penalty-rules/",
                                rule_payload(brand, early_termination_months="30.00"), format="json")

    assert refused.status_code == 400
    assert "can't be more than 24 months" in str(refused.data["early_termination_months"])


@pytest.mark.parametrize("months", ["0", "-1.00"])
def test_zero_or_negative_months_are_still_refused(admin_client, brand, months):
    response = admin_client.post("/api/policy/contract-penalty-rules/",
                                 rule_payload(brand, early_termination_months=months), format="json")

    assert response.status_code == 400
    assert "early_termination_months" in response.data


def test_editing_the_default_rule_past_the_cap_is_refused(admin_client):
    default = ContractPenaltyRule.objects.get(brand__isnull=True, is_active=True)

    response = admin_client.patch(f"/api/policy/contract-penalty-rules/{default.pk}/",
                                  {"early_termination_months": "37.00"}, format="json")

    assert response.status_code == 400
    default.refresh_from_db()
    assert default.early_termination_months <= 36


def test_the_django_admin_form_applies_the_cap(rf, admin_user, brand):
    form =admin_form(ContractPenaltyRule, rf, admin_user)(data={
        **rule_payload(brand, early_termination_months="60.00"), "source_note": "", "is_active": True,
    })

    assert not form.is_valid()
    assert form.errors["early_termination_months"] == [
        "The early-return fee can't be more than 36 months of fee - the longest subscription plan is 36 months."
    ]


# --- F-16 -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "RM0.50 per km is used here for the Alphard.",
    "Wear on the alphard is checked at return.",          # any case
    "Applies to the ALPHARD 2.4 only.",
])
def test_a_brand_rule_naming_its_own_model_is_refused(admin_client, text):
    toyota = Brand.objects.create(name="ToyotaX", tier_code="3")
    make_car(toyota, name="Alphard", trim="2.4 Executive Lounge")

    response = admin_client.post("/api/policy/contract-penalty-rules/",
                                 rule_payload(toyota, wear_tear_tolerance_description=text), format="json")

    assert response.status_code == 400
    assert response.data["wear_tear_tolerance_description"][0].startswith(
        "Do not name a model here - this rule applies to every car of the brand (found: Alphard")


def test_the_brands_own_name_and_other_words_are_fine(admin_client):
    lexus = Brand.objects.create(name="LexusX", tier_code="2")
    make_car(lexus, name="ES", trim="250 Luxury")

    response = admin_client.post("/api/policy/contract-penalty-rules/", rule_payload(
        lexus, wear_tear_tolerance_description="LexusX KINTO ONE: licences, yes and express servicing included."),
        format="json")

    assert response.status_code == 201, response.data


def test_the_default_rule_is_not_checked_against_a_brand(admin_client):
    default = ContractPenaltyRule.objects.get(brand__isnull=True, is_active=True)
    make_car(Brand.objects.create(name="AnyBrand", tier_code="2"), name="Alphard")

    response = admin_client.patch(f"/api/policy/contract-penalty-rules/{default.pk}/",
                                  {"wear_tear_tolerance_description": "Typical terms (KINTO ONE, Alphard)."},
                                  format="json")

    assert response.status_code == 200, response.data


def test_the_django_admin_form_refuses_a_model_name(rf, admin_user):
    toyota = Brand.objects.create(name="ToyotaY", tier_code="3")
    make_car(toyota, name="Alphard", trim="2.4 Executive Lounge")
    form = admin_form(ContractPenaltyRule, rf, admin_user)(data={
        **rule_payload(toyota, wear_tear_tolerance_description="Used here for the alphard."),
        "source_note": "", "is_active": True,
    })

    assert not form.is_valid()
    assert "Do not name a model here" in str(form.errors["wear_tear_tolerance_description"])


LIVE = json.loads((Path(__file__).parent / "fixtures" / "live_contract_rule_texts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("brand_name", sorted(LIVE["texts"]))
def test_the_six_live_texts_pass_the_new_guard(brand_name):
    """The fixture guard's own regression set: the write-path check (any case) leaves every live text alone."""
    names = model_name_candidates(LIVE["models"].get(brand_name, []))

    assert model_name_in_text_message(LIVE["texts"][brand_name], names) is None


# --- F-12 -----------------------------------------------------------------------------------------------------------

POLICY_TABLES = {
    ResidualBaseline: ResidualBaselineReadSerializer,
    ResidualAdjustment: ResidualAdjustmentReadSerializer,
    SubscriptionPolicy: SubscriptionPolicyReadSerializer,
    RoadTaxCcBand: RoadTaxCcBandReadSerializer,
    EvRoadTaxGroup: EvRoadTaxGroupReadSerializer,
    OperatingCostRate: OperatingCostRateReadSerializer,
}


def test_the_message_is_the_one_asked_for():
    assert FUTURE_EFFECTIVE_FROM_MESSAGE == (
        "Scheduled (future-dated) policy rows are not supported; use today's date or earlier."
    )


@pytest.mark.parametrize("model", list(POLICY_TABLES), ids=lambda m: m.__name__)
def test_every_policy_admin_form_refuses_a_future_date_and_says_so(rf, admin_user, model):
    row = model.objects.order_by("pk").first()  # a seeded row
    assert row is not None, f"no seeded {model.__name__} row"
    form_class = admin_form(model, rf, admin_user, instance=row)
    tomorrow = timezone.localdate() + datetime.timedelta(days=1)

    unchanged = form_class(instance=row)
    data = {name: unchanged[name].value() for name in unchanged.fields}
    data = {k: ("" if v is None else v) for k, v in data.items()}

    future = form_class(data={**data, "effective_from": tomorrow.isoformat()}, instance=row)
    assert not future.is_valid()
    assert future.errors["effective_from"] == [FUTURE_EFFECTIVE_FROM_MESSAGE]
    assert unchanged.fields["effective_from"].help_text == FUTURE_EFFECTIVE_FROM_MESSAGE

    # the row as stored (dated in the past) is still valid, and today is allowed
    assert form_class(data=data, instance=row).is_valid(), form_class(data=data, instance=row).errors
    today = form_class(data={**data, "effective_from": timezone.localdate().isoformat()}, instance=row)
    assert today.is_valid(), today.errors


@pytest.mark.parametrize("model, serializer_class", list(POLICY_TABLES.items()), ids=lambda m: getattr(m, "__name__", ""))
def test_every_policy_serializer_refuses_a_future_date(model, serializer_class):
    row = model.objects.order_by("pk").first()
    tomorrow = timezone.localdate() + datetime.timedelta(days=1)

    future = serializer_class(row, data={"effective_from": tomorrow.isoformat()}, partial=True)
    assert not future.is_valid()
    assert future.errors["effective_from"] == [FUTURE_EFFECTIVE_FROM_MESSAGE]

    past = serializer_class(row, data={"effective_from": row.effective_from.isoformat()}, partial=True)
    assert past.is_valid(), past.errors
    assert serializer_class().fields["effective_from"].help_text == FUTURE_EFFECTIVE_FROM_MESSAGE
