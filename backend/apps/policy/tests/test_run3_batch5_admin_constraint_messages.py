"""Run 3 fix batch 5 (F-14): a save the database would refuse is still refused in
Django admin, but in plain words - never 'Constraint "..." is violated.'. The
subscription policy form has its own clean() for shortest > longest; the other
policy forms (and the vehicles forms, checked as neighbours) word every constraint
the same way."""

import pytest
from django.contrib.admin.sites import site
from django.urls import resolve, reverse

from apps.policy.admin_forms import (
    CONSTRAINT_MESSAGES,
    GENERIC_CONSTRAINT_MESSAGE,
    SHORTEST_LONGER_THAN_LONGEST,
    plain_constraint_message,
)
from apps.policy.models import (
    ContractPenaltyRule,
    EvRoadTaxGroup,
    InterestRate,
    OperatingCostRate,
    ResidualAdjustment,
    ResidualBaseline,
    ResidualValueMatrix,
    RoadTaxCcBand,
    SubscriptionPlan,
    SubscriptionPolicy,
)
from apps.vehicles.models import Brand, VehicleModel

pytestmark = pytest.mark.django_db


def admin_request(model, rf, user, instance=None):
    meta = model._meta
    url = (reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[instance.pk]) if instance is not None
           else reverse(f"admin:{meta.app_label}_{meta.model_name}_add"))
    request = rf.get(url)
    request.user = user
    request.resolver_match = resolve(url)
    return request


def form_for(model, rf, user, data, instance=None):
    request = admin_request(model, rf, user, instance)
    form_class = site._registry[model].get_form(request, obj=instance)
    return form_class(data=data, instance=instance)


def data_from(model, rf, user, instance, **changes):
    request = admin_request(model, rf, user, instance)
    unbound = site._registry[model].get_form(request, obj=instance)(instance=instance)
    data = {name: unbound[name].value() for name in unbound.fields}
    data = {k: ("" if v is None else v) for k, v in data.items()}
    data.update(changes)
    return data


def all_errors(form):
    return [str(m) for errors in form.errors.values() for m in errors]


def test_the_subscription_policy_shortest_longer_than_longest(rf, admin_user):
    policy = SubscriptionPolicy.objects.get(is_active=True)
    form = form_for(SubscriptionPolicy, rf, admin_user,
                    data_from(SubscriptionPolicy, rf, admin_user, policy, min_tenure_months=40, max_tenure_months=36),
                    instance=policy)

    assert not form.is_valid()
    assert all_errors(form) == [SHORTEST_LONGER_THAN_LONGEST]
    assert SHORTEST_LONGER_THAN_LONGEST == "The shortest plan cannot be longer than the longest plan."


def test_a_road_tax_band_with_min_above_max(rf, admin_user):
    band = RoadTaxCcBand.objects.filter(is_active=True).order_by("pk").first()
    form = form_for(RoadTaxCcBand, rf, admin_user,
                    data_from(RoadTaxCcBand, rf, admin_user, band, min_cc=3000, max_cc=1000), instance=band)

    assert not form.is_valid()
    assert all_errors(form) == ["The lowest cc cannot be above the highest cc."]


def test_a_second_active_operating_cost_rate_for_a_powertrain(rf, admin_user):
    existing = OperatingCostRate.objects.filter(is_active=True).order_by("pk").first()
    data = data_from(OperatingCostRate, rf, admin_user, existing)
    form = form_for(OperatingCostRate, rf, admin_user, data)  # a NEW row with the same powertrain

    assert not form.is_valid()
    assert all_errors(form) == ["There is already an active rate for this powertrain. Archive it first, then add "
                                "the replacement."]


def test_a_residual_adjustment_with_both_a_brand_and_a_powertrain(rf, admin_user):
    brand = Brand.objects.create(name="AdjBrand", tier_code="2")
    adjustment = ResidualAdjustment.objects.filter(is_active=True, brand__isnull=True).order_by("pk").first()
    form = form_for(ResidualAdjustment, rf, admin_user,
                    data_from(ResidualAdjustment, rf, admin_user, adjustment, brand=brand.pk), instance=adjustment)

    assert not form.is_valid()
    assert "Choose either a brand or a powertrain - one of the two." in all_errors(form)


@pytest.mark.parametrize("model", [
    InterestRate, ResidualValueMatrix, ResidualBaseline, ResidualAdjustment, SubscriptionPlan, SubscriptionPolicy,
    RoadTaxCcBand, EvRoadTaxGroup, OperatingCostRate, ContractPenaltyRule,
], ids=lambda m: m.__name__)
def test_every_policy_admin_form_words_constraints_plainly(rf, admin_user, model):
    request = rf.get("/admin/")
    request.user = admin_user
    form_class = site._registry[model].get_form(request)

    assert any(base.__name__ == "PlainConstraintMessagesForm" for base in form_class.__mro__)


def test_every_named_policy_constraint_has_a_plain_sentence():
    names = {constraint.name for model in (InterestRate, ResidualValueMatrix, ResidualBaseline, ResidualAdjustment,
                                           SubscriptionPlan, SubscriptionPolicy, RoadTaxCcBand, EvRoadTaxGroup,
                                           OperatingCostRate, ContractPenaltyRule)
             for constraint in model._meta.constraints}

    assert names <= set(CONSTRAINT_MESSAGES)


def test_an_unknown_constraint_still_reads_plainly():
    assert plain_constraint_message('Constraint "some_future_rule" is violated.') == GENERIC_CONSTRAINT_MESSAGE
    assert plain_constraint_message("Constraint “some_future_rule” is violated.") == GENERIC_CONSTRAINT_MESSAGE
    assert plain_constraint_message("Enter a number.") == "Enter a number."


def test_the_vehicle_form_shows_no_constraint_name_for_an_electric_car_with_cc(rf, admin_user):
    """Neighbour check (vehicles admin): its own clean() already words the bev rule."""
    brand = Brand.objects.create(name="EvBrand", tier_code="1")
    car = VehicleModel.objects.create(brand=brand, name="E", trim="X", body_segment="suv", msrp="500000.00",
                                      engine_capacity_kw="250.00", powertrain="bev")
    form = form_for(VehicleModel, rf, admin_user,
                    data_from(VehicleModel, rf, admin_user, car, engine_capacity_cc=1998), instance=car)

    assert not form.is_valid()
    assert not any("Constraint" in m and "is violated" in m for m in all_errors(form))
