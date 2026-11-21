import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from apps.ml.models import MLTrainingRun, ProductionModel, TrainingRunStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def csv_upload(
    rows, header="vehicle_age,mileage,resale_price,brand_code,engine_litres,body_type,recond,model_key",
    filename="upload.csv",
):
    lines = [header] + rows
    content = "\n".join(lines).encode("utf-8")
    return SimpleUploadedFile(filename, content, content_type="text/csv")


def valid_rows(n=60):
    # Enough rows, spread across ages/brands, for train_test_split(test_size=0.2)
    # to have a non-trivial test set; values follow a simple learnable trend.
    rows = []
    for i in range(n):
        age = i % 10
        brand = 1 + (i % 3)
        mileage = age * 12000
        price = max(1000, 100000 - age * 8000 - brand * 2000)
        body = ("sedan", "suv", "hatchback")[i % 3]
        rows.append(f"{age},{mileage},{price},{brand},2.0,{body},0,Brand{brand} {body}")
    return rows


def test_upload_requires_admin_role(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    upload = csv_upload(valid_rows())

    response = client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_upload_rejects_unauthenticated():
    client = APIClient()
    upload = csv_upload(valid_rows())

    response = client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Malformed CSV alternate flow (UC012 3.1-3.4) ---------------------------


def test_malformed_csv_rejected_with_no_training_run_created(admin_client):
    upload = csv_upload(["2,20000,45000"], header="vehicle_age,mileage,resale_price")  # missing brand_code

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Missing required columns" in response.data["detail"]
    assert "brand_code" in response.data["detail"]
    assert MLTrainingRun.objects.count() == 0


def test_malformed_csv_leaves_existing_production_model_untouched(admin_client):
    production = ProductionModel.get_singleton()
    production.model_type = "random_forest"
    production.model_file_path = "/fake/path/existing_model.joblib"
    production.r2_score = 0.91
    production.save()

    upload = csv_upload(["2,20000,45000"], header="vehicle_age,mileage,resale_price")
    admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    production.refresh_from_db()
    assert production.model_file_path == "/fake/path/existing_model.joblib"
    assert production.r2_score == 0.91


def test_upload_requires_a_file(admin_client):
    response = admin_client.post("/api/ml/datasets/", {}, format="multipart")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- QA audit L18: upload size limit and concurrent-retrain guard ----------


def test_upload_past_the_size_limit_is_rejected(admin_client, settings):
    settings.ML_DATASET_MAX_UPLOAD_SIZE_BYTES = 100
    upload = csv_upload(valid_rows(n=40))  # comfortably over 100 bytes

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "size limit" in response.data["detail"]
    assert MLTrainingRun.objects.count() == 0


def test_upload_at_or_under_the_size_limit_is_accepted(admin_client, settings):
    settings.ML_DATASET_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
    upload = csv_upload(valid_rows(n=40))

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_202_ACCEPTED


def test_upload_rejected_while_a_run_is_already_running(admin_client):
    MLTrainingRun.objects.create(status=TrainingRunStatus.RUNNING)
    upload = csv_upload(valid_rows(n=40))

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert MLTrainingRun.objects.filter(status=TrainingRunStatus.RUNNING).count() == 1


# --- M10: invalid-value rows and too-small datasets reject 400, not 500 -----


def test_csv_with_a_few_invalid_value_rows_rejects_400_and_leaves_everything_untouched(admin_client):
    """Negative mileage (row 2) is numerically valid for pd.to_numeric
    (it's a real float) but semantically nonsensical - previously this
    sailed through straight into sklearn and crashed as an unhandled 500."""
    rows = valid_rows(n=40)
    rows[0] = "2,-12000,45000,1,2.0,sedan,0,Brand1 sedan"  # negative mileage
    upload = csv_upload(rows)

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "invalid value" in response.data["detail"]
    assert MLTrainingRun.objects.count() == 0


def test_csv_with_an_infinite_value_rejects_400(admin_client):
    rows = valid_rows(n=40)
    rows[0] = "2,20000,inf,1,2.0,sedan,0,Brand1 sedan"
    upload = csv_upload(rows)

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert MLTrainingRun.objects.count() == 0


def test_too_small_csv_rejects_400_instead_of_500(admin_client):
    """5 well-formed rows - every value is valid, there just aren't enough
    of them for a meaningful 80/20 split + 3-fold GridSearchCV. Previously
    this reached train_and_evaluate anyway and raised from inside sklearn
    as an unhandled 500."""
    upload = csv_upload(valid_rows(n=5))

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "30" in response.data["detail"]
    assert MLTrainingRun.objects.count() == 0


# --- Well-formed CSV: training runs (CELERY_TASK_ALWAYS_EAGER=True) --------


def test_valid_upload_creates_and_completes_a_training_run(admin_client, admin_user):
    upload = csv_upload(valid_rows())

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_202_ACCEPTED
    run = MLTrainingRun.objects.get(pk=response.data["id"])
    assert run.status == TrainingRunStatus.SUCCEEDED
    assert run.triggered_by_id == admin_user.id
    assert run.rf_r2 is not None
    assert run.gb_r2 is not None
    # ML batch 1: the run says what it predicted, and measured the second R².
    assert run.prediction_target == "log_resale_price"
    assert response.data["prediction_target_label"] == "Resale price (log scale)"
    assert "rf_within_model_r2" in response.data and "gb_within_model_r2" in response.data


# --- ML batch 1: the new schema's rules through the endpoint ------------------------------------


def test_an_old_msrp_proxy_csv_is_refused_with_the_missing_columns_message(admin_client):
    rows = [f"{i % 10},{(i % 10) * 12000},{90000 - i},{1 + i % 3},60000" for i in range(40)]
    upload = csv_upload(rows, header="vehicle_age,mileage,resale_price,brand_code,msrp_proxy")

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["detail"] == (
        "Dataset upload failed. Missing required columns: [body_type, engine_litres, recond]."
    )
    assert MLTrainingRun.objects.count() == 0


def test_an_unknown_body_type_is_refused_before_any_run_is_created(admin_client):
    rows = valid_rows(n=40)
    rows[3] = "2,24000,80000,1,2.0,roadster,0,Brand1 roadster"
    upload = csv_upload(rows)

    response = admin_client.post("/api/ml/datasets/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["detail"] == (
        "Dataset upload failed. 1 row(s) have a body_type that is not one of sedan, hatchback, suv, mpv, pickup, "
        "coupe: row(s) [5]."
    )
    assert MLTrainingRun.objects.count() == 0
