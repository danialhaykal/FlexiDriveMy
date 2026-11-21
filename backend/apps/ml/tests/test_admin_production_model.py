"""QA audit H3: ProductionModel.model_file_path must not be freely
retargetable via Django admin - apps/depreciation/inference.py unpickles
whatever that path points to on the next request, so an admin-writable
path is arbitrary code execution, and it would skip the R2 >= 0.80
deployment gate entirely (apps.ml.tasks._deploy is the only path meant
to ever change this row).
"""

import pytest
from django.test import Client
from django.urls import reverse

from apps.ml.models import ModelType, ProductionModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_django_client(django_user_model):
    user = django_user_model.objects.create_superuser(email="superadmin@example.com", password="pw")
    client = Client()
    client.force_login(user)
    return client


def test_production_model_change_form_is_not_editable(admin_django_client):
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = "ml_models/legit_model.joblib"
    production.save()

    change_url = reverse("admin:ml_productionmodel_change", args=[production.pk])
    response = admin_django_client.post(
        change_url,
        {"model_type": ModelType.GRADIENT_BOOSTING, "model_file_path": "/etc/passwd"},
    )

    # has_change_permission() = False -> Django admin refuses the POST
    # outright, never touching the row.
    assert response.status_code == 403
    production.refresh_from_db()
    assert production.model_file_path == "ml_models/legit_model.joblib"
    assert production.model_type == ModelType.RANDOM_FOREST


def test_production_model_cannot_be_added_or_deleted_via_admin(admin_django_client):
    add_url = reverse("admin:ml_productionmodel_add")
    response = admin_django_client.get(add_url)
    assert response.status_code == 403

    production = ProductionModel.get_singleton()
    delete_url = reverse("admin:ml_productionmodel_delete", args=[production.pk])
    response = admin_django_client.post(delete_url, {"post": "yes"})
    assert response.status_code == 403
    assert ProductionModel.objects.filter(pk=production.pk).exists()
