"""Run 2 fix batch 3 (A5): the Max DSR limit is 1 to 100 percent everywhere - the
Financial Profile, the AI Recommendation request, the DSR simulator and a saved
scenario's inputs - from ONE validator pair and ONE sentence."""

import pytest
from rest_framework.test import APIClient

from apps.common.constants import DSR_RANGE_MESSAGE, dsr_limit_validators
from apps.policy.models import MileageBand
from apps.profiles.serializers import FinancialProfileSerializer
from apps.scenarios.serializers import ScenarioScoringInputsSerializer
from apps.scoring.serializers import DSRSimulatorRequestSerializer, SuitabilityScoringRequestSerializer
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

SENTENCE = "Max DSR limit must be between 1 and 100 percent."


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def vehicle():
    brand = Brand.objects.create(name="DsrRangeBrand", tier_code="A")
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SUV, msrp="100000.00",
        engine_capacity_kw="90.00",
    )


def params(vehicle, **overrides):
    base = {
        "vehicle": vehicle.pk, "tenure_months": 36, "mileage_band": MileageBand.STANDARD, "downpayment": "10000.00",
        "monthly_income": "10000.00", "max_dsr_percent": "40",
        "upfront_cash_preservation": 5, "maintenance_protection": 3, "ownership_equity": 2,
    }
    base.update(overrides)
    return base


def test_the_sentence_is_the_one_the_profile_always_used():
    assert DSR_RANGE_MESSAGE == SENTENCE


@pytest.mark.parametrize("url", ["/api/scoring/", "/api/scoring/dsr-simulator/"])
@pytest.mark.parametrize("value", ["0", "0.50", "0.99", "100.01", "101", "1000", "99999", "abc"])
def test_a_limit_outside_1_to_100_is_refused_with_the_same_sentence(user_client, vehicle, url, value):
    response = user_client.get(url, params(vehicle, max_dsr_percent=value))

    assert response.status_code == 400
    assert response.data["max_dsr_percent"] == [SENTENCE]


@pytest.mark.parametrize("url", ["/api/scoring/", "/api/scoring/dsr-simulator/"])
@pytest.mark.parametrize("value", ["1", "1.00", "60", "100", "100.00"])
def test_the_edges_of_the_range_are_not_refused_for_the_limit(user_client, vehicle, url, value):
    response = user_client.get(url, params(vehicle, max_dsr_percent=value))

    # The car has no rate/residual config here, so the call may still be refused for other
    # reasons; what matters is that the limit itself is accepted.
    assert "max_dsr_percent" not in (response.data if response.status_code == 400 else {})


def test_every_entry_point_uses_the_same_validators_not_a_copy():
    """One definition: the same validator class, bounds and message on all four fields."""

    def signature(field):
        return [
            (type(v).__name__, v.limit_value, v.message)
            for v in field.validators
            if type(v).__name__ in ("MinValueValidator", "MaxValueValidator")
        ]

    expected = [(type(v).__name__, v.limit_value, v.message) for v in dsr_limit_validators()]
    fields = [
        FinancialProfileSerializer().fields["max_dsr_percent"],
        SuitabilityScoringRequestSerializer().fields["max_dsr_percent"],
        DSRSimulatorRequestSerializer().fields["max_dsr_percent"],
        ScenarioScoringInputsSerializer().fields["max_dsr_percent"],
    ]

    for field in fields:
        assert signature(field) == expected
        assert field.error_messages["invalid"] == SENTENCE


def test_a_saved_scenarios_recommendation_inputs_follow_the_same_range():
    serializer = ScenarioScoringInputsSerializer(data={
        "upfront_cash_preservation": 5, "maintenance_protection": 3, "ownership_equity": 2,
        "monthly_income": "10000", "max_dsr_percent": "0",
    })

    assert not serializer.is_valid()
    assert serializer.errors["max_dsr_percent"] == [SENTENCE]
