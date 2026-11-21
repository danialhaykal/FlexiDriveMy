"""Run 2 fix batch 3 (D1, X2, A5): DRF's own number/choice sentences become plain
ones - once, centrally. Unit tests for the helper, then one API test per example
the buyer or admin can reach (Fleet price / kW / model year, the affordability
simulator's 11-digit income, the Financial Profile's unknown mileage band)."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.test import APIClient

from apps.common.error_messages import plain_error_messages
from apps.policy.models import MileageBand
from apps.vehicles.models import BodySegment, Brand, VehicleModel


def errors_of(serializer_class, data):
    serializer = serializer_class(data=data)
    assert not serializer.is_valid()
    return plain_error_messages(serializer.errors)


# --- the helper, one DRF code at a time -----------------------------------------------------------------------


class Numbers(serializers.Serializer):
    whole = serializers.IntegerField()
    decimal = serializers.DecimalField(max_digits=12, decimal_places=2)
    decimal_one_place = serializers.DecimalField(max_digits=12, decimal_places=1, required=False)
    short = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    ratio = serializers.FloatField(required=False)
    choice = serializers.ChoiceField(choices=[("a", "A"), ("b", "B")], required=False)


def test_invalid_numbers_get_plain_sentences():
    errors = errors_of(Numbers, {"whole": "abc", "decimal": "abc", "ratio": "abc"})

    assert errors["whole"] == ["Please enter a whole number."]
    assert errors["decimal"] == ["Please enter a valid number."]
    assert errors["ratio"] == ["Please enter a valid number."]


def test_too_many_digits_names_the_fields_real_limit():
    # max_digits 12 with 2 decimals -> 10 whole digits (the field's own limit, not a typed constant).
    errors = errors_of(Numbers, {"whole": 1, "decimal": "12345678901"})

    assert errors["decimal"] == ["That number is too large. Use at most 10 digits before the decimal point."]


def test_total_digit_limit_has_its_own_plain_sentence():
    errors = errors_of(Numbers, {"whole": 1, "decimal": "1", "short": "1.234"})
    total = errors_of(Numbers, {"whole": 1, "decimal": "1", "short": "12345.1"})

    assert errors["short"] == ["Please use at most 2 decimal places."]
    # 12345.1 -> 5 digits + 1 decimal = 6 > max_digits 5
    assert total["short"] == ["That number is too large. Use at most 5 digits in total."]


def test_decimal_places_are_singular_for_one():
    errors = errors_of(Numbers, {"whole": 1, "decimal": "1.234", "decimal_one_place": "1.25"})

    assert errors["decimal"] == ["Please use at most 2 decimal places."]
    assert errors["decimal_one_place"] == ["Please use at most 1 decimal place."]


def test_an_unknown_choice_gets_a_plain_sentence():
    errors = errors_of(Numbers, {"whole": 1, "decimal": "1", "choice": "zzz"})

    assert errors["choice"] == ["Choose one of the available options."]


def test_codes_survive_the_rewrite():
    serializer = Numbers(data={"whole": "abc", "decimal": "12345678901", "choice": "zzz"})
    serializer.is_valid()
    plain = plain_error_messages(serializer.errors)

    assert [e.code for e in plain["whole"]] == ["invalid"]
    assert [e.code for e in plain["decimal"]] == ["max_whole_digits"]
    assert [e.code for e in plain["choice"]] == ["invalid_choice"]
    assert all(isinstance(e, ErrorDetail) for e in plain["whole"])


def test_messages_a_serializer_wrote_are_never_touched():
    class Written(serializers.Serializer):
        price = serializers.DecimalField(
            max_digits=12, decimal_places=2, error_messages={"invalid": "MSRP must be a positive numeric value."}
        )
        kind = serializers.ChoiceField(choices=["x"], error_messages={"invalid_choice": "Choose a kind."})

    errors = errors_of(Written, {"price": "abc", "kind": "q"})

    assert errors["price"] == ["MSRP must be a positive numeric value."]
    assert errors["kind"] == ["Choose a kind."]


def test_the_invalid_code_on_other_field_types_gets_its_own_sentence():
    """`invalid` is shared by dates, e-mail and booleans: each gets its own plain sentence, never a
    number sentence. (Run 2 batch 3 left these three alone; Run 3 batch 5, F-02, words them.)"""

    class Mixed(serializers.Serializer):
        when = serializers.DateField()
        mail = serializers.EmailField()
        flag = serializers.BooleanField()

    serializer = Mixed(data={"when": "not a date", "mail": "nope", "flag": "maybe"})
    serializer.is_valid()
    plain = plain_error_messages(serializer.errors)

    assert plain["when"] == ["Enter a date in the format YYYY-MM-DD."]
    assert plain["mail"] == ["Enter a valid email address, for example name@example.com."]
    assert plain["flag"] == ["Flag must be true or false."]


def test_a_non_default_text_with_a_matching_code_is_left_alone():
    detail = ErrorDetail("Mileage must be a number.", code="invalid")

    assert plain_error_messages({"mileage": [detail]})["mileage"][0] == "Mileage must be a number."


def test_nested_and_list_errors_keep_their_shape():
    class Row(serializers.Serializer):
        amount = serializers.DecimalField(max_digits=12, decimal_places=2)

    class Outer(serializers.Serializer):
        rows = Row(many=True)
        inner = Row()

    serializer = Outer(data={"rows": [{"amount": "1"}, {"amount": "abc"}], "inner": {"amount": "abc"}})
    serializer.is_valid()
    plain = plain_error_messages(serializer.errors)

    assert plain["rows"][0] == {}
    assert plain["rows"][1] == {"amount": ["Please enter a valid number."]}
    assert plain["inner"] == {"amount": ["Please enter a valid number."]}


def test_non_error_data_passes_through():
    assert plain_error_messages({"detail": "Not found."}) == {"detail": "Not found."}
    assert plain_error_messages(None) is None
    assert plain_error_messages(5) == 5


def test_the_handler_rewrites_a_raised_validation_error():
    from apps.audit.runtime_errors import api_exception_handler

    exc = ValidationError({"amount": [ErrorDetail("A valid number is required.", code="invalid")]})
    response = api_exception_handler(exc, {"request": None})

    assert response.status_code == 400
    assert response.data == {"amount": ["Please enter a valid number."]}


# --- the API, one example per place a buyer or admin sees it ----------------------------------------------------


@pytest.mark.django_db
class TestFleetForm:
    @pytest.fixture
    def admin_client(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        return client

    @pytest.fixture
    def payload(self):
        brand = Brand.objects.create(name="PlainWording", tier_code="2")
        return {
            "brand": brand.pk, "name": "M", "trim": "X", "body_segment": "sedan", "msrp": "100000.00",
            "engine_capacity_kw": "100.00", "powertrain": "petrol", "engine_capacity_cc": 1998,
        }

    def test_a_price_that_is_not_a_number(self, admin_client, payload):
        response = admin_client.post("/api/vehicles/models/", {**payload, "msrp": "abc"}, format="json")

        assert response.status_code == 400
        assert response.data["msrp"] == ["Please enter a valid number."]

    def test_a_power_output_that_is_not_a_number(self, admin_client, payload):
        response = admin_client.post("/api/vehicles/models/", {**payload, "engine_capacity_kw": "lots"}, format="json")

        assert response.status_code == 400
        assert response.data["engine_capacity_kw"] == ["Please enter a valid number."]

    def test_a_model_year_that_is_not_a_whole_number(self, admin_client, payload):
        response = admin_client.post("/api/vehicles/models/", {**payload, "model_year": "20x6"}, format="json")

        assert response.status_code == 400
        assert response.data["model_year"] == ["Please enter a whole number."]

    def test_a_price_with_too_many_digits_names_the_limit(self, admin_client, payload):
        response = admin_client.post("/api/vehicles/models/", {**payload, "msrp": "12345678901"}, format="json")

        assert response.status_code == 400
        assert "That number is too large. Use at most 10 digits before the decimal point." in response.data["msrp"]

    def test_messages_the_fleet_serializer_wrote_are_unchanged(self, admin_client, payload):
        response = admin_client.post("/api/vehicles/models/", {**payload, "msrp": "0"}, format="json")
        bad_segment = admin_client.post("/api/vehicles/models/", {**payload, "body_segment": "boat"}, format="json")

        assert response.data["msrp"] == ["MSRP must be a positive numeric value."]
        assert bad_segment.data["body_segment"] == ["Choose a body segment."]

    def test_a_bulk_import_row_error_reads_the_same(self, admin_client):
        Brand.objects.create(name="Lexus", tier_code="1")
        csv = (
            "brand,name,trim,body_segment,msrp,engine_capacity_kw,powertrain,engine_capacity_cc,model_year\n"
            "Lexus,RX,350h,suv,lots,184.00,hybrid,2487,\n"
        ).encode()

        response = admin_client.post(
            "/api/vehicles/models/bulk_import/", {"file": SimpleUploadedFile("cars.csv", csv)}, format="multipart"
        )

        assert response.status_code == 200
        assert response.data["error_count"] == 1
        assert response.data["errors"][0]["errors"]["msrp"] == ["Please enter a valid number."]


@pytest.mark.django_db
class TestAffordabilitySimulator:
    def test_an_income_with_11_digits_says_the_real_limit(self, regular_user):
        client = APIClient()
        client.force_authenticate(user=regular_user)
        brand = Brand.objects.create(name="SimBrand", tier_code="A")
        car = VehicleModel.objects.create(
            brand=brand, name="Model", trim="X", body_segment=BodySegment.SUV, msrp="100000.00",
            engine_capacity_kw="90.00",
        )

        response = client.get("/api/scoring/dsr-simulator/", {
            "vehicle": car.pk, "tenure_months": 36, "mileage_band": MileageBand.STANDARD,
            "downpayment": "10000.00", "monthly_income": "12345678901", "max_dsr_percent": "40",
        })

        assert response.status_code == 400
        assert response.data["monthly_income"] == [
            "That number is too large. Use at most 10 digits before the decimal point."
        ]

    def test_a_downpayment_that_is_not_a_number_keeps_its_own_sentence(self, regular_user):
        client = APIClient()
        client.force_authenticate(user=regular_user)
        brand = Brand.objects.create(name="SimBrand", tier_code="A")
        car = VehicleModel.objects.create(
            brand=brand, name="Model", trim="X", body_segment=BodySegment.SUV, msrp="100000.00",
            engine_capacity_kw="90.00",
        )

        response = client.get("/api/scoring/dsr-simulator/", {
            "vehicle": car.pk, "tenure_months": 36, "mileage_band": "extreme",
            "downpayment": "abc", "monthly_income": "10000", "max_dsr_percent": "40",
        })

        assert response.data["downpayment"] == ["Please enter a valid positive numerical amount."]
        assert response.data["mileage_band"] == ["Choose one of the available options."]


@pytest.mark.django_db
class TestFinancialProfile:
    PROFILE = {"monthly_budget": "5000.00", "preferred_tenure_months": 48, "annual_mileage_band": "standard",
               "ownership_preference": "retain", "shariah_compliant_required": False}

    def test_an_unknown_mileage_band(self, regular_user):
        client = APIClient()
        client.force_authenticate(user=regular_user)

        response = client.put(
            "/api/profile/financial/", {**self.PROFILE, "annual_mileage_band": "extreme"}, format="json"
        )

        assert response.status_code == 400
        assert response.data["annual_mileage_band"] == ["Choose one of the available options."]

    def test_a_dsr_limit_that_is_not_a_number_keeps_the_range_sentence(self, regular_user):
        client = APIClient()
        client.force_authenticate(user=regular_user)

        response = client.put("/api/profile/financial/", {**self.PROFILE, "max_dsr_percent": "abc"}, format="json")

        assert response.data["max_dsr_percent"] == ["Max DSR limit must be between 1 and 100 percent."]


def test_decimal_is_still_exact_after_the_rewrite():
    """The helper only rewrites text: values and validated data are untouched."""
    serializer = Numbers(data={"whole": "7", "decimal": "10.50"})

    assert serializer.is_valid()
    assert serializer.validated_data["decimal"] == Decimal("10.50")
