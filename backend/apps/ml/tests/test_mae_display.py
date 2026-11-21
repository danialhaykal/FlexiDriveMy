"""The ML run table's MAE is shown in the unit that run was measured in.

ML batch 1: every run records its own prediction_target (older runs were
backfilled by migration 0009), and the unit comes from that field - the old
"every MAE <= 1 means a ratio" guess in the serializer is gone:
  log_resale_price      -> "typical error ≈ 22% of price" ((e^MAE - 1) x 100)
  value_retention_ratio -> "10.0 pts of price"
  raw_resale_price      -> "RM 15,881.93"
The figures below are the real dev-database runs."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.ml.models import MLTrainingRun, PredictionTarget, ProductionModel
from apps.ml.serializers import (
    MAE_UNIT_LOG_PRICE,
    MAE_UNIT_POINTS_OF_PRICE,
    MAE_UNIT_RM,
    MLTrainingRunSerializer,
    format_mae,
)

pytestmark = pytest.mark.django_db

URL = "/api/ml/training-runs/"
LOG = PredictionTarget.LOG_RESALE_PRICE
RATIO = PredictionTarget.VALUE_RETENTION_RATIO
RAW = PredictionTarget.RAW_RESALE_PRICE


def make_run(rf_mae, gb_mae, target, **kwargs):
    return MLTrainingRun.objects.create(
        status="succeeded", rf_mae=rf_mae, gb_mae=gb_mae, prediction_target=target, **kwargs
    )


def data(run):
    return MLTrainingRunSerializer(run).data


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


# --- the formatter ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, shown",
    [
        (0.2022, "typical error ≈ 22% of price"),   # the reference GB run: e^0.2022 - 1 = 22.41%
        (0.1966, "typical error ≈ 22% of price"),   # e^0.1966 - 1 = 21.73%
        (0.0, "typical error ≈ 0% of price"),
        (0.1, "typical error ≈ 11% of price"),      # 10.52%
        (0.4055, "typical error ≈ 50% of price"),   # 50.01%
    ],
)
def test_a_log_price_error_is_shown_as_a_typical_share_of_the_price(value, shown):
    assert format_mae(value, MAE_UNIT_LOG_PRICE) == shown


@pytest.mark.parametrize(
    "value, shown",
    [
        (0.0998827768, "10.0 pts of price"),   # the 5 Oct run's RF MAE
        (0.0950027839, "9.5 pts of price"),    # the 3 Oct run's RF MAE
        (0.0911167369, "9.1 pts of price"),
        (0.0445, "4.5 pts of price"),          # one decimal, half-up
        (0.0444, "4.4 pts of price"),
    ],
)
def test_a_ratio_error_is_shown_as_points_of_the_price_with_one_decimal(value, shown):
    assert format_mae(value, MAE_UNIT_POINTS_OF_PRICE) == shown


@pytest.mark.parametrize(
    "value, shown",
    [(15881.927565105385, "RM 15,881.93"), (1271.4343860916672, "RM 1,271.43"), (30797.419639583113, "RM 30,797.42")],
)
def test_a_raw_price_error_keeps_the_rm_display(value, shown):
    assert format_mae(value, MAE_UNIT_RM) == shown


def test_an_absurd_log_error_is_shown_as_stored_never_a_crash():
    assert format_mae(900.0, MAE_UNIT_LOG_PRICE) == "log-scale error 900.0000"
    # (e^25 - 1) x 100 = 7,200,489,933,638.59 -> half-up, with separators
    assert format_mae(25.0, MAE_UNIT_LOG_PRICE) == "typical error ≈ 7,200,489,933,639% of price"


def test_no_mae_means_no_display():
    assert format_mae(None, MAE_UNIT_RM) is None
    assert format_mae(0.1, None) is None


# --- each run's unit comes from its own recorded target -------------------------------------


def test_the_dev_databases_real_runs_each_get_the_right_unit_and_display():
    run1 = make_run(1271.4343860916672, 1386.5429491882994, RAW)
    run8 = make_run(0.09988277687010295, 0.09517399933593718, RATIO)
    run9 = make_run(0.1966, 0.2022, LOG)

    assert (data(run1)["mae_unit"], data(run1)["rf_mae_display"], data(run1)["gb_mae_display"]) == (
        "rm", "RM 1,271.43", "RM 1,386.54")
    assert (data(run8)["mae_unit"], data(run8)["rf_mae_display"], data(run8)["gb_mae_display"]) == (
        "points_of_price", "10.0 pts of price", "9.5 pts of price")
    assert (data(run9)["mae_unit"], data(run9)["rf_mae_display"], data(run9)["gb_mae_display"]) == (
        "log_price", "typical error ≈ 22% of price", "typical error ≈ 22% of price")


def test_the_unit_is_the_runs_own_target_never_a_guess_from_the_size_of_the_number():
    # Small numbers, but the run says it predicted raw prices: RM, as recorded.
    small_raw = make_run(0.5, 0.6, RAW)
    # A log-price MAE is also <= 1 - the old rule would have called it "points".
    log_run = make_run(0.2022, 0.1966, LOG)

    assert data(small_raw)["mae_unit"] == "rm"
    assert data(log_run)["mae_unit"] == "log_price"


def test_a_run_with_metrics_but_no_recorded_target_shows_no_unit():
    run = make_run(0.0998, 0.0952, "")

    shown = data(run)

    assert (shown["mae_unit"], shown["rf_mae_display"], shown["gb_mae_display"]) == (None, None, None)
    assert shown["rf_mae"] == 0.0998  # the stored value is still sent


def test_a_run_with_no_mae_has_no_unit_and_no_display():
    run = MLTrainingRun.objects.create(status="failed", error_message="boom")

    shown = data(run)

    assert (shown["mae_unit"], shown["rf_mae_display"], shown["gb_mae_display"]) == (None, None, None)


def test_one_estimator_missing_its_mae_still_displays_the_other():
    run = make_run(0.0998, None, RATIO)

    shown = data(run)

    assert (shown["rf_mae_display"], shown["gb_mae_display"], shown["mae_unit"]) == (
        "10.0 pts of price", None, "points_of_price")


def test_the_raw_stored_mae_values_are_unchanged():
    run = make_run(0.09988277687010295, 0.09517399933593718, RATIO)

    assert data(run)["rf_mae"] == 0.09988277687010295 and data(run)["gb_mae"] == 0.09517399933593718


def test_the_run_carries_its_target_label_both_r2_values_and_retirement():
    run = make_run(0.1966, 0.2022, LOG, rf_r2=0.8673, gb_r2=0.8789, rf_within_model_r2=0.5487,
                   gb_within_model_r2=0.6489, retired_reason="")

    shown = data(run)

    assert shown["prediction_target"] == "log_resale_price"
    assert shown["prediction_target_label"] == "Resale price (log scale)"
    assert (shown["rf_r2"], shown["rf_within_model_r2"]) == (0.8673, 0.5487)
    assert (shown["gb_r2"], shown["gb_within_model_r2"]) == (0.8789, 0.6489)
    assert (shown["retired_at"], shown["retired_reason"]) == (None, "")


# --- the serving note follows the current target ------------------------------------------------


def test_the_serving_note_names_what_a_refused_production_model_predicts():
    run = make_run(0.0998, 0.0952, RATIO)
    ProductionModel.objects.update_or_create(
        pk=1, defaults={"training_run": run, "model_type": "random_forest", "prediction_target": RATIO,
                        "model_file_path": "C:/models/x.joblib"},
    )

    assert data(run)["serving_note"] == (
        f"Run {run.pk} is marked deployed but is not used: it predicts value-retention ratios, and the "
        "forecast now needs the resale-price model (log scale)."
    )

    ProductionModel.objects.filter(pk=1).update(prediction_target=LOG)
    assert data(run)["serving_note"] is None


# --- the endpoint ----------------------------------------------------------------------------


def test_the_run_list_endpoint_carries_the_display_fields(admin_client):
    make_run(15881.93, 15598.68, RAW)
    make_run(0.0998, 0.0952, RATIO)
    make_run(0.2022, 0.1966, LOG)

    response = admin_client.get(URL)

    assert response.status_code == status.HTTP_200_OK
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    assert {r["rf_mae_display"] for r in rows} == {
        "RM 15,881.93", "10.0 pts of price", "typical error ≈ 22% of price"}
    assert {r["mae_unit"] for r in rows} == {"rm", "points_of_price", "log_price"}


def test_the_list_costs_one_production_lookup_not_one_per_run(admin_client, django_assert_max_num_queries):
    for _ in range(6):
        make_run(0.0998, 0.0952, RATIO)

    with django_assert_max_num_queries(8):
        admin_client.get(URL)


# --- the production card endpoint -------------------------------------------------------------


def test_the_production_endpoint_shows_the_served_models_target_and_both_r2(admin_client):
    run = make_run(0.1966, 0.2022, LOG, rf_r2=0.8673, gb_r2=0.8789, rf_within_model_r2=0.5487,
                   gb_within_model_r2=0.6489)
    ProductionModel.objects.update_or_create(
        pk=1, defaults={"training_run": run, "model_type": "gradient_boosting", "prediction_target": LOG,
                        "model_file_path": "C:/models/x.joblib", "r2_score": 0.8789, "mae": 0.2022},
    )

    body = admin_client.get("/api/ml/production-model/").data

    assert body["training_run"] == run.pk
    assert body["prediction_target_label"] == "Resale price (log scale)"
    assert (body["r2_score"], body["within_model_r2"]) == (0.8789, 0.6489)
    assert body["mae_display"] == "typical error ≈ 22% of price"
    assert body["is_serving"] is True


def test_the_run_carries_the_log_linear_candidate_and_the_curve_check(admin_client):
    """ML batch 2: the third candidate and the curve check, in the run's own unit."""
    run = make_run(0.2012, 0.2005, LOG, ll_r2=0.9124, ll_mae=0.1473, ll_within_model_r2=0.7199,
                   ll_best_params={"alpha": 0.3857}, curve_check_passed=True, curve_check_report=[])
    older = make_run(0.0998, 0.0952, RATIO)

    rows = {r["id"]: r for r in admin_client.get(URL).data["results"]}

    shown = rows[run.pk]
    assert (shown["ll_r2"], shown["ll_within_model_r2"], shown["ll_best_params"]) == (0.9124, 0.7199, {"alpha": 0.3857})
    assert shown["ll_mae_display"] == "typical error ≈ 16% of price"  # e^0.1473 - 1 = 15.87%
    assert (shown["curve_check_passed"], shown["curve_check_report"]) == (True, [])
    assert (rows[older.pk]["curve_check_passed"], rows[older.pk]["ll_mae_display"]) == (None, None)


def test_the_production_endpoint_names_a_deployed_log_linear_model(admin_client):
    run = make_run(0.2012, 0.2005, LOG, ll_r2=0.9124, ll_mae=0.1473, ll_within_model_r2=0.7199)
    ProductionModel.objects.update_or_create(
        pk=1, defaults={"training_run": run, "model_type": "log_linear", "prediction_target": LOG,
                        "model_file_path": "C:/models/x.joblib", "r2_score": 0.9124, "mae": 0.1473},
    )

    body = admin_client.get("/api/ml/production-model/").data

    assert body["model_type_label"] == "Log-linear (hedonic)"
    assert (body["r2_score"], body["within_model_r2"]) == (0.9124, 0.7199)


def test_the_production_endpoint_with_nothing_deployed(admin_client):
    body = admin_client.get("/api/ml/production-model/").data

    assert body["training_run"] is None
    assert body["prediction_target"] == ""
    assert body["within_model_r2"] is None
    assert body["is_serving"] is False


def test_the_production_endpoint_is_admin_only(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)

    assert client.get("/api/ml/production-model/").status_code == status.HTTP_403_FORBIDDEN
