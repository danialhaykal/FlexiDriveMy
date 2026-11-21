from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditActionCategory, AuditLog
from apps.policy.models import MCDACriteriaWeight, MCDACriterion

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def full_weights_payload(**overrides):
    weights = {
        MCDACriterion.UPFRONT_CASH_PRESERVATION: "0.4000",
        MCDACriterion.MAINTENANCE_PROTECTION: "0.3000",
        MCDACriterion.OWNERSHIP_EQUITY: "0.3000",
    }
    weights.update(overrides)
    return {"weights": [{"criterion": criterion, "default_weight": weight} for criterion, weight in weights.items()]}


def test_get_returns_seeded_defaults(admin_client):
    response = admin_client.get("/api/policy/mcda-weights/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) == 3
    total = sum(float(row["default_weight"]) for row in response.data)
    assert round(total, 4) == 1.0


def test_put_replaces_all_weights_when_they_sum_to_one(admin_client):
    response = admin_client.put("/api/policy/mcda-weights/", full_weights_payload(), format="json")

    assert response.status_code == status.HTTP_200_OK
    weight = MCDACriteriaWeight.objects.get(criterion=MCDACriterion.UPFRONT_CASH_PRESERVATION)
    assert weight.default_weight == Decimal("0.4000")


def test_put_rejects_weights_that_do_not_sum_to_one(admin_client):
    payload = full_weights_payload(**{MCDACriterion.UPFRONT_CASH_PRESERVATION: "0.5000"})

    response = admin_client.put("/api/policy/mcda-weights/", payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "sum to 1.0" in str(response.data)


def test_put_rejects_missing_criterion(admin_client):
    payload = full_weights_payload()
    payload["weights"] = payload["weights"][:2]  # drop one criterion

    response = admin_client.put("/api/policy/mcda-weights/", payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_put_requires_admin_role(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    response = client.put("/api/policy/mcda-weights/", full_weights_payload(), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_put_writes_audit_log(admin_client, admin_user):
    admin_client.put("/api/policy/mcda-weights/", full_weights_payload(), format="json")

    log = AuditLog.objects.get(action=AuditActionCategory.UPDATE, resource_type="policy.MCDACriteriaWeight")
    assert log.actor_id == admin_user.id
    assert len(log.after_data["weights"]) == 3
