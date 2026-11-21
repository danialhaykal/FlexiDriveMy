"""Run 3 fix batch 5 (F-02, F-04, F-05): the rest of DRF's default sentences become
plain ones that name the field, through the same central mapper - keyed on the
error code AND DRF's own default text, so a message a serializer wrote is never
touched; keys, nesting, codes and status codes are unchanged.

Unit tests per code, then one API test per example recorded in the Run 3 log.
"""

from decimal import Decimal

import pytest
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.test import APIClient

from apps.common.error_messages import plain_error_messages, readable_label, serializer_labels
from apps.policy.models import InterestRate, ResidualValueMatrix
from apps.users.serializers import DUPLICATE_EMAIL_MESSAGE
from apps.users.validators import PHONE_NUMBER_MESSAGE
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db


class Probe(serializers.Serializer):
    name = serializers.CharField(max_length=5, required=False)
    short = serializers.CharField(min_length=3, required=False)
    tenure_months = serializers.IntegerField(min_value=12, max_value=108, required=False)
    price = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("0"), required=False)
    vehicle = serializers.PrimaryKeyRelatedField(queryset=VehicleModel.objects.all(), required=False)
    vehicles = serializers.PrimaryKeyRelatedField(queryset=VehicleModel.objects.all(), many=True, required=False,
                                                  allow_empty=False)
    site = serializers.URLField(required=False)
    email = serializers.EmailField(required=False)
    flag = serializers.BooleanField(required=False)
    max_dsr_percent = serializers.IntegerField(required=False)
    text = serializers.CharField(required=False, allow_null=False)
    labelled = serializers.CharField(label="Confirm password")


def errors_for(data, labels=None):
    serializer = Probe(data=data)
    assert not serializer.is_valid()
    return plain_error_messages(serializer.errors, labels=labels), serializer.errors


# --- one rule per code ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("data, key, expected", [
    ({}, "labelled", "Labelled is required."),                                         # required
    ({"text": None, "labelled": "x"}, "text", "Text is required."),                   # null
    ({"text": "", "labelled": "x"}, "text", "Text is required."),                     # blank
    ({"name": "toolong", "labelled": "x"}, "name", "Name can be at most 5 characters long."),       # max_length
    ({"short": "ab", "labelled": "x"}, "short", "Short must be at least 3 characters long."),        # min_length
    ({"tenure_months": 6, "labelled": "x"}, "tenure_months", "Tenure months must be 12 or more."),  # min_value
    ({"tenure_months": 200, "labelled": "x"}, "tenure_months", "Tenure months must be 108 or less."),  # max_value
    ({"price": "-1", "labelled": "x"}, "price", "Price must be 0 or more."),          # min_value (decimal)
    ({"vehicle": 999999, "labelled": "x"}, "vehicle", "The selected vehicle does not exist or is no longer available."),
    ({"vehicle": {"a": 1}, "labelled": "x"}, "vehicle", "Choose a valid vehicle."),   # incorrect_type
    ({"vehicles": "x", "labelled": "x"}, "vehicles", "Vehicles must be a list."),     # not_a_list
    ({"vehicles": [], "labelled": "x"}, "vehicles", "Choose at least one option."),   # empty
    ({"site": "nope", "labelled": "x"}, "site", "Enter a valid web address, starting with http:// or https://."),
    ({"email": "not-an-email", "labelled": "x"}, "email", "Enter a valid email address, for example name@example.com."),
    ({"flag": "maybe", "labelled": "x"}, "flag", "Flag must be true or false."),
])
def test_each_default_sentence_becomes_a_plain_one(data, key, expected):
    plain, raw = errors_for(data)

    assert plain[key] == [expected]
    assert plain[key][0].code == raw[key][0].code  # the code survives


def test_the_label_is_the_serializers_own_when_given():
    plain, _ = errors_for({}, labels=serializer_labels(Probe))

    assert plain["labelled"] == ["Confirm password is required."]


def test_a_readable_label_keeps_short_forms():
    assert readable_label("max_dsr_percent") == "Max DSR percent"
    assert readable_label("msrp") == "MSRP"
    assert readable_label("engine_capacity_kw") == "Engine capacity kW"
    assert readable_label("downpayment") == "Downpayment"


def test_a_non_field_error_says_this_value():
    detail = ErrorDetail(serializers.Field.default_error_messages["required"], code="required")

    assert plain_error_messages({"non_field_errors": [detail]}) == {"non_field_errors": ["This value is required."]}


def test_a_unique_set_names_the_fields_in_words():
    detail = ErrorDetail("The fields brand, tenure_months, mileage_band must make a unique set.", code="unique")

    assert plain_error_messages({"non_field_errors": [detail]})["non_field_errors"] == [
        "A record with this brand, tenure months and mileage band already exists."]


def test_the_model_unique_sentence_gets_an_article_and_a_capital():
    detail = ErrorDetail("brand with this name already exists.", code="unique")

    assert plain_error_messages({"name": [detail]})["name"] == ["A brand with this name already exists."]


@pytest.mark.parametrize("text, code", [
    ("A user with that email already exists.", "invalid"),
    ("A brand with this name already exists.", "unique"),       # capitalised: written by hand
    ("Tenure must be between 12 and 108 months.", "min_value"),
    ("Please enter a valid positive numerical amount.", "min_value"),
    ("Choose a month from 1 to 36.", "invalid"),
])
def test_messages_a_serializer_wrote_are_never_touched(text, code):
    assert plain_error_messages({"x": [ErrorDetail(text, code=code)]})["x"] == [text]


def test_the_handler_names_the_field_and_keeps_the_status():
    from apps.audit.runtime_errors import api_exception_handler

    exc = ValidationError({"title": [ErrorDetail("This field is required.", code="required")]})
    response = api_exception_handler(exc, {"request": None, "view": None})

    assert response.status_code == 400
    assert response.data == {"title": ["Title is required."]}


# --- the API: one example per entry in the Run 3 log ----------------------------------------------------------------


@pytest.fixture
def buyer(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


@pytest.fixture
def admin(admin_user):
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


@pytest.fixture
def car():
    brand = Brand.objects.create(name="WordingBrand", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="2.8000")
    return VehicleModel.objects.create(
        brand=brand, name="M", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00",
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )


def test_comparison_without_a_vehicle(buyer):
    response = buyer.get("/api/comparisons/", {"tenure_months": 36, "mileage_band": "standard", "downpayment": "30000"})

    assert response.status_code == 400
    assert response.data["vehicle"] == ["Vehicle is required."]


def test_comparison_with_a_vehicle_that_does_not_exist(buyer):
    response = buyer.get("/api/comparisons/", {"vehicle": 999999, "tenure_months": 36, "mileage_band": "standard",
                                               "downpayment": "30000"})

    assert response.status_code == 400
    assert response.data["vehicle"] == ["The selected vehicle does not exist or is no longer available."]


def test_a_residual_override_for_6_months(admin, car):
    response = admin.post("/api/policy/residual-value-matrix/", {
        "brand": car.brand_id, "tenure_months": 6, "mileage_band": "standard", "residual_value_ratio": "0.5000",
    }, format="json")

    assert response.status_code == 400
    assert response.data["tenure_months"] == ["Tenure months must be 12 or more."]


def test_a_second_override_for_the_same_brand_tenure_and_band(admin, car):
    ResidualValueMatrix.objects.create(brand=car.brand, tenure_months=36, mileage_band="standard",
                                       residual_value_ratio="0.5000")

    response = admin.post("/api/policy/residual-value-matrix/", {
        "brand": car.brand_id, "tenure_months": 36, "mileage_band": "standard", "residual_value_ratio": "0.4000",
    }, format="json")

    assert response.status_code == 400
    assert response.data == {
        "non_field_errors": ["A record with this brand, tenure months and mileage band already exists."]}


def test_a_saved_scenario_title_of_151_characters(buyer, car):
    response = buyer.post("/api/scenarios/", {
        "title": "x" * 151, "vehicle": car.pk,
        "inputs": {"tenure_months": 36, "mileage_band": "standard", "downpayment": "30000.00", "include_tco": False,
                   "scoring": None},
    }, format="json")

    assert response.status_code == 400
    assert response.data["title"] == ["Title can be at most 150 characters long."]


def test_register_with_an_email_that_is_not_one(api_client):
    response = api_client.post("/api/auth/register/", {
        "email": "not-an-email", "password": "StrongPassw0rd!23", "password2": "StrongPassw0rd!23",
    }, format="json")

    assert response.status_code == 400
    assert response.data["email"] == ["Enter a valid email address, for example name@example.com."]


def test_register_without_the_confirmation_uses_its_label(api_client):
    response = api_client.post("/api/auth/register/", {"email": "a@example.com", "password": "StrongPassw0rd!23"},
                               format="json")

    assert response.status_code == 400
    assert response.data["password2"] == ["Confirm password is required."]


@pytest.mark.parametrize("value, word", [(0, "1 or more"), (6, "5 or less"), (-1, "1 or more")])
def test_scoring_ratings_out_of_range(buyer, car, value, word):
    response = buyer.get("/api/scoring/", {
        "vehicle": car.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "30000.00",
        "upfront_cash_preservation": value, "maintenance_protection": 3, "ownership_equity": 3,
        "monthly_income": "20000", "max_dsr_percent": "60",
    })

    assert response.status_code == 400
    assert response.data["upfront_cash_preservation"] == [f"Upfront cash preservation must be {word}."]


def test_sandbox_with_a_negative_excess(buyer, car):
    response = buyer.get("/api/depreciation/total-loss-sandbox/", {
        "vehicle": car.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "30000.00",
        "loss_month": 18, "excess_amount": "-1",
    })

    assert response.status_code == 400
    assert response.data["excess_amount"] == ["Excess amount must be 0 or more."]


# --- F-04: one duplicate-email sentence, any letter case --------------------------------------------------------------


@pytest.mark.parametrize("email", ["rider@example.com", "RIDER@EXAMPLE.COM", "Rider@Example.com"])
def test_a_duplicate_email_gets_one_sentence_whatever_its_case(api_client, regular_user, email):
    response = api_client.post("/api/auth/register/", {
        "email": email, "password": "StrongPassw0rd!23", "password2": "StrongPassw0rd!23",
    }, format="json")

    assert response.status_code == 400
    assert response.data["email"] == [DUPLICATE_EMAIL_MESSAGE]
    assert DUPLICATE_EMAIL_MESSAGE == "An account with this email already exists."


# --- F-05: one phone rule for registration and the profile update ----------------------------------------------------


@pytest.mark.parametrize("phone", ["call-me", "12345", "(((((((", "+60 12-345 6789 ext 2", "123456789012345678901"])
def test_a_bad_phone_number_is_refused_on_register_and_profile(api_client, regular_user, phone):
    register = api_client.post("/api/auth/register/", {
        "email": "new.person@example.com", "password": "StrongPassw0rd!23", "password2": "StrongPassw0rd!23",
        "phone_number": phone,
    }, format="json")
    api_client.force_authenticate(user=regular_user)
    profile = api_client.patch("/api/auth/profile/", {"phone_number": phone}, format="json")

    assert register.status_code == 400 and register.data["phone_number"] == [PHONE_NUMBER_MESSAGE]
    assert profile.status_code == 400 and profile.data["phone_number"] == [PHONE_NUMBER_MESSAGE]


@pytest.mark.parametrize("phone", ["+60 12-345 6789", "012-3456789", "(03) 2345 6789", "+60123456789", ""])
def test_a_good_or_empty_phone_number_is_accepted(api_client, regular_user, phone):
    api_client.force_authenticate(user=regular_user)

    response = api_client.patch("/api/auth/profile/", {"phone_number": phone}, format="json")

    assert response.status_code == 200, response.data
    regular_user.refresh_from_db()
    assert regular_user.phone_number == phone


def test_the_phone_message_is_the_one_asked_for():
    assert PHONE_NUMBER_MESSAGE == "Enter a valid phone number, for example +60 12-345 6789."
