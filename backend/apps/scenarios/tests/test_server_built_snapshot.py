"""Run 1 fix batch 2 (G6): a saved scenario's figures are calculated by the
server from the inputs, with the same services and serializers as the live
endpoints - a client can no longer send (or forge) a figure.

The JSON-equality tests compare the stored snapshot with what the live GET
endpoints return for the same inputs and user, byte for byte after JSON
decoding. Vehicle: BMW 3 Series 320i Sport (RM 265,800, 2.8% flat), 60 months,
standard band, downpayment 26,580.00, ratings 4/3/2, income 8,000, DSR limit 40.
"""

import importlib
import json

import pytest
from django.apps import apps as django_apps
from rest_framework import status
from rest_framework.test import APIClient

from apps.comparisons.services import RATE_NOT_SET_MESSAGE
from apps.policy.models import InterestRate
from apps.profiles.models import FinancialProfile
from apps.scenarios.models import SavedScenario
from apps.scenarios.serializers import FIGURES_ARE_FIXED_MESSAGE, PAYLOAD_NOT_ACCEPTED_MESSAGE
from apps.scoring.formulas import INCOMPLETE_QUIZ_MESSAGE
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")

SCORING = {
    "upfront_cash_preservation": 4,
    "maintenance_protection": 3,
    "ownership_equity": 2,
    "monthly_income": "8000",
    "max_dsr_percent": "40",
}
INPUTS = {
    "tenure_months": 60,
    "mileage_band": "standard",
    "downpayment": "26580.00",
    "include_tco": True,
    "scoring": SCORING,
}
LIVE_QUERY = {"tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00"}


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
def no_rate_car():
    brand = Brand.objects.create(name="NoRateBrand", tier_code="2")
    return VehicleModel.objects.create(
        brand=brand, name="M", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00",
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )


@pytest.fixture
def client(regular_user):
    # A profile that declares "high" mileage (so the TCO's declared-mileage
    # alert is in play) and prefers Islamic financing wording.
    FinancialProfile.objects.create(
        user=regular_user, monthly_budget="5000.00", preferred_tenure_months=60,
        annual_mileage_band="high", ownership_preference="retain", shariah_compliant_required=True,
    )
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


def save(client, vehicle, title="R1-2 check", inputs=INPUTS, **extra):
    return client.post(
        "/api/scenarios/", {"title": title, "vehicle": vehicle.id, "inputs": inputs, **extra}, format="json"
    )


def live(client, path, **params):
    response = client.get(path, params)
    assert response.status_code == 200, response.content
    return json.loads(response.content)


# --- the snapshot equals the live screens -------------------------------------------------------------


def test_the_saved_comparison_tco_and_scoring_equal_the_live_endpoints_exactly(client, bmw, regular_user):
    response = save(client, bmw)

    assert response.status_code == status.HTTP_201_CREATED, response.content
    payload = SavedScenario.objects.get(user=regular_user, title="R1-2 check").payload
    assert payload["comparison"] == live(client, "/api/comparisons/", vehicle=bmw.id, **LIVE_QUERY)
    assert payload["tco"] == live(client, "/api/depreciation/tco/", vehicle=bmw.id, **LIVE_QUERY)
    assert payload["scoring"] == live(client, "/api/scoring/", vehicle=bmw.id, **LIVE_QUERY, **SCORING)


def test_the_snapshot_keeps_the_old_keys_and_records_who_built_it(client, bmw, regular_user):
    save(client, bmw)
    payload = SavedScenario.objects.get(user=regular_user).payload

    assert payload["snapshotVersion"] == 2
    assert payload["builtBy"] == "server"
    assert (payload["tenureMonths"], payload["mileageBand"], payload["downpayment"]) == (60, "standard", "26580.00")
    assert payload["prefersIslamicFinancing"] is True  # from the user's own profile, not the request
    assert "tcoUnavailableReason" not in payload
    assert payload["inputs"] == {
        "tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00", "include_tco": True,
        "ncd_percent": "0.00",  # from the profile at save time (run 1 fix batch 3)
        "scoring": {"upfront_cash_preservation": 4, "maintenance_protection": 3, "ownership_equity": 2,
                    "monthly_income": "8000.00", "max_dsr_percent": "40.00"},
    }
    # the figures this batch must not move (Run 3 fix batch 6 recalibrated the standard band:
    # the balloon and net were 93,030.00 / 245,367.80 on the old 0.35 residual)
    assert payload["comparison"]["hire_purchase"]["monthly_instalment"] == "4545.18"
    assert payload["comparison"]["gfv_leasing"]["balloon_payment"] == "97787.82"
    assert payload["tco"]["tco_net"] == "240609.98"


def test_tco_and_scoring_are_null_when_those_tabs_were_not_used(client, bmw, regular_user):
    save(client, bmw, inputs={**INPUTS, "include_tco": False, "scoring": None})
    payload = SavedScenario.objects.get(user=regular_user).payload

    assert payload["tco"] is None and payload["scoring"] is None
    assert payload["inputs"]["include_tco"] is False and payload["inputs"]["scoring"] is None


def test_include_tco_defaults_to_false_and_scoring_is_optional(client, bmw, regular_user):
    response = save(client, bmw, inputs={"tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00"})

    assert response.status_code == status.HTTP_201_CREATED
    assert SavedScenario.objects.get(user=regular_user).payload["tco"] is None


def test_islamic_wording_is_left_out_when_the_profile_does_not_ask_for_it(client, bmw, regular_user):
    FinancialProfile.objects.filter(user=regular_user).update(shariah_compliant_required=False)
    save(client, bmw)

    assert "prefersIslamicFinancing" not in SavedScenario.objects.get(user=regular_user).payload


def test_a_brand_with_no_interest_rate_still_saves(client, no_rate_car, regular_user):
    response = save(client, no_rate_car, inputs={**INPUTS, "downpayment": "30000.00", "scoring": None})

    assert response.status_code == status.HTTP_201_CREATED, response.content
    payload = SavedScenario.objects.get(user=regular_user).payload
    assert payload["tco"] is None
    assert payload["tcoUnavailableReason"] == RATE_NOT_SET_MESSAGE
    assert payload["comparison"]["hire_purchase"] is None and payload["comparison"]["gfv_leasing"] is None
    assert payload["comparison"] == live(
        client, "/api/comparisons/", vehicle=no_rate_car.id, tenure_months=60, mileage_band="standard",
        downpayment="30000.00",
    )


# --- a client can't send figures --------------------------------------------------------------------


def test_a_forged_payload_is_refused_with_the_reason(client, bmw, regular_user):
    forged = {"comparison": {"hire_purchase": {"monthly_instalment": "1.00"}}}

    response = save(client, bmw, payload=forged)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["payload"] == [PAYLOAD_NOT_ACCEPTED_MESSAGE]
    assert not SavedScenario.objects.filter(user=regular_user).exists()


def test_an_old_tab_sending_only_a_payload_learns_why(client, bmw):
    response = client.post(
        "/api/scenarios/", {"title": "Old tab", "vehicle": bmw.id, "payload": {"tenureMonths": 60}}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {"payload": [PAYLOAD_NOT_ACCEPTED_MESSAGE]}


def test_inputs_are_required_on_create(client, bmw):
    response = client.post("/api/scenarios/", {"title": "No inputs", "vehicle": bmw.id}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "inputs" in response.data


# --- inputs follow the live request rules ----------------------------------------------------------------


def test_a_downpayment_below_ten_percent_is_refused_as_on_the_live_endpoint(client, bmw):
    response = save(client, bmw, inputs={**INPUTS, "downpayment": "1000.00"})
    live_response = client.get("/api/comparisons/", {"vehicle": bmw.id, **LIVE_QUERY, "downpayment": "1000.00"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["inputs"]["downpayment"] == live_response.data["downpayment"]


def test_a_tenure_outside_the_range_is_refused_as_on_the_live_endpoint(client, bmw):
    response = save(client, bmw, inputs={**INPUTS, "tenure_months": 120})
    live_response = client.get("/api/comparisons/", {"vehicle": bmw.id, **LIVE_QUERY, "tenure_months": 120})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["inputs"]["tenure_months"] == live_response.data["tenure_months"]


def test_an_unrated_priority_is_a_400_as_on_the_live_endpoint(client, bmw, regular_user):
    scoring = {key: value for key, value in SCORING.items() if key != "ownership_equity"}

    response = save(client, bmw, inputs={**INPUTS, "scoring": scoring})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["inputs"]["scoring"]["priorities"] == [INCOMPLETE_QUIZ_MESSAGE]
    assert not SavedScenario.objects.filter(user=regular_user).exists()


def test_a_scoring_request_without_income_is_refused(client, bmw):
    scoring = {key: value for key, value in SCORING.items() if key != "monthly_income"}

    response = save(client, bmw, inputs={**INPUTS, "scoring": scoring})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "monthly_income" in response.data["inputs"]["scoring"]


# --- overwrite, rename, ownership, old rows -----------------------------------------------------------------


def test_the_overwrite_path_is_server_built(client, bmw, regular_user):
    old = SavedScenario.objects.create(
        user=regular_user, title="Family Car", vehicle=bmw,
        payload={"comparison": {"hire_purchase": {"monthly_instalment": "1.00"}}},
    )

    response = save(client, bmw, title="Family Car", overwrite="true")

    assert response.status_code == status.HTTP_200_OK
    old.refresh_from_db()
    assert old.payload["builtBy"] == "server"
    assert old.payload["comparison"]["hire_purchase"]["monthly_instalment"] == "4545.18"
    assert SavedScenario.objects.filter(user=regular_user).count() == 1


def test_a_duplicate_title_is_still_a_409_and_nothing_is_built_or_changed(client, bmw, regular_user):
    old = SavedScenario.objects.create(user=regular_user, title="Family Car", vehicle=bmw, payload={"old": True})

    response = save(client, bmw, title="family car")

    assert response.status_code == status.HTTP_409_CONFLICT
    old.refresh_from_db()
    assert old.payload == {"old": True}


def test_renaming_keeps_the_payload_untouched(client, bmw, regular_user):
    save(client, bmw, title="Before")
    scenario = SavedScenario.objects.get(user=regular_user)
    payload_before = scenario.payload

    response = client.patch(f"/api/scenarios/{scenario.pk}/", {"title": "After"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    scenario.refresh_from_db()
    assert scenario.title == "After"
    assert scenario.payload == payload_before


def test_a_put_with_the_same_vehicle_renames_too(client, bmw, regular_user):
    save(client, bmw, title="Before")
    scenario = SavedScenario.objects.get(user=regular_user)

    response = client.put(f"/api/scenarios/{scenario.pk}/", {"title": "After", "vehicle": bmw.id}, format="json")

    assert response.status_code == status.HTTP_200_OK
    scenario.refresh_from_db()
    assert scenario.title == "After"


@pytest.mark.parametrize("method", ["patch", "put"])
def test_inputs_on_an_update_are_refused(client, bmw, regular_user, method):
    save(client, bmw, title="Before")
    scenario = SavedScenario.objects.get(user=regular_user)
    payload_before = scenario.payload

    response = getattr(client, method)(
        f"/api/scenarios/{scenario.pk}/",
        {"title": "After", "vehicle": bmw.id, "inputs": {**INPUTS, "tenure_months": 36}},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["inputs"] == [FIGURES_ARE_FIXED_MESSAGE]
    scenario.refresh_from_db()
    assert (scenario.title, scenario.payload) == ("Before", payload_before)


def test_a_payload_on_an_update_is_refused(client, bmw, regular_user):
    save(client, bmw, title="Before")
    scenario = SavedScenario.objects.get(user=regular_user)

    response = client.patch(f"/api/scenarios/{scenario.pk}/", {"payload": {"tco": None}}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["payload"] == [PAYLOAD_NOT_ACCEPTED_MESSAGE]


def test_changing_the_vehicle_on_an_update_is_refused(client, bmw, no_rate_car, regular_user):
    save(client, bmw, title="Before")
    scenario = SavedScenario.objects.get(user=regular_user)

    response = client.patch(f"/api/scenarios/{scenario.pk}/", {"vehicle": no_rate_car.id}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    scenario.refresh_from_db()
    assert scenario.vehicle_id == bmw.id


def test_another_users_scenario_is_still_a_404(bmw, regular_user, create_user):
    scenario = SavedScenario.objects.create(user=regular_user, title="Mine", vehicle=bmw, payload={"old": True})
    intruder = APIClient()
    intruder.force_authenticate(user=create_user(email="intruder@example.com"))

    assert intruder.get(f"/api/scenarios/{scenario.pk}/").status_code == status.HTTP_404_NOT_FOUND
    assert intruder.patch(
        f"/api/scenarios/{scenario.pk}/", {"title": "Hijacked"}, format="json"
    ).status_code == status.HTTP_404_NOT_FOUND


def test_an_old_format_row_still_serializes_exactly_as_saved(client, bmw, regular_user):
    old_payload = {
        "tenureMonths": 36, "mileageBand": "standard", "downpayment": "40000.00",
        "comparison": {"hire_purchase": {"monthly_instalment": "10900.00", "early_termination_amount": "3.00"}},
        "tco": None, "scoring": None,
    }
    scenario = SavedScenario.objects.create(user=regular_user, title="Old", vehicle=bmw, payload=old_payload)

    response = client.get(f"/api/scenarios/{scenario.pk}/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["payload"] == old_payload
    assert "inputs" not in response.data  # write-only


def test_the_size_cap_still_applies_to_the_built_payload(client, bmw, regular_user, monkeypatch):
    monkeypatch.setattr("apps.scenarios.serializers.MAX_PAYLOAD_BYTES", 100)

    response = save(client, bmw)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "too large" in str(response.data["payload"])
    assert not SavedScenario.objects.filter(user=regular_user).exists()
