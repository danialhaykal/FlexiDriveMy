"""Sprint 13 addendum - confirms the leaky-run annotation data fix matches
exactly the one confirmed run and touches nothing else (see
apps/ml/data_fixes.py and apps/ml/migrations/0004_annotate_leaky_msrp_proxy_run.py).
"""

import pytest

from apps.ml.data_fixes import KNOWN_ISSUE_NOTE_LEAKY_MSRP_PROXY_RUN, leaky_msrp_proxy_run_queryset
from apps.ml.models import MLTrainingRun

pytestmark = pytest.mark.django_db


def _make_run(**overrides):
    defaults = {
        "status": "succeeded",
        "dataset_filename": "real_historical_pricing.csv",
        "rf_r2": 0.5,
        "deployed": False,
        "deployed_model_type": "",
    }
    defaults.update(overrides)
    return MLTrainingRun.objects.create(**defaults)


def test_queryset_matches_only_the_specific_leaky_run_by_its_recorded_metrics():
    # The real id=4 run's own recorded figures.
    leaky_run = _make_run(rf_r2=0.9334544740842177, deployed=True, deployed_model_type="random_forest")
    # A close neighbor that must NOT match: right dataset/deployed/type, but
    # a materially different R2 (the real id=5 run's own figures).
    close_but_different_r2 = _make_run(
        rf_r2=0.8920486727513421, deployed=True, deployed_model_type="random_forest"
    )
    # Right R2 range, but not deployed - must not match.
    right_r2_not_deployed = _make_run(rf_r2=0.9335, deployed=False, deployed_model_type="")
    # Right R2 and deployed, but the wrong dataset - must not match.
    right_r2_wrong_dataset = _make_run(
        dataset_filename="synthetic_historical_pricing.csv",
        rf_r2=0.9335,
        deployed=True,
        deployed_model_type="random_forest",
    )
    # Right R2 and dataset, but deployed under the other model type - must not match.
    right_r2_wrong_model_type = _make_run(
        rf_r2=0.9335, deployed=True, deployed_model_type="gradient_boosting"
    )

    matched = list(leaky_msrp_proxy_run_queryset(MLTrainingRun))

    assert matched == [leaky_run]
    for run in (close_but_different_r2, right_r2_not_deployed, right_r2_wrong_dataset, right_r2_wrong_model_type):
        assert run not in matched


def test_annotating_the_leaky_run_leaves_every_other_run_and_field_untouched():
    leaky_run = _make_run(
        rf_r2=0.9334544740842177,
        deployed=True,
        deployed_model_type="random_forest",
        rejection_reason="",
        error_message="",
        row_count=888,
    )
    other_run_1 = _make_run(rf_r2=0.8920486727513421, deployed=True, deployed_model_type="random_forest")
    other_run_2 = _make_run(rf_r2=0.6549551754870522, deployed=False, deployed_model_type="")

    run = leaky_msrp_proxy_run_queryset(MLTrainingRun).get()
    run.known_issue_note = KNOWN_ISSUE_NOTE_LEAKY_MSRP_PROXY_RUN
    run.save(update_fields=["known_issue_note"])

    leaky_run.refresh_from_db()
    other_run_1.refresh_from_db()
    other_run_2.refresh_from_db()

    assert leaky_run.known_issue_note == KNOWN_ISSUE_NOTE_LEAKY_MSRP_PROXY_RUN
    assert other_run_1.known_issue_note == ""
    assert other_run_2.known_issue_note == ""

    # Every other field on the annotated run itself is exactly as it was -
    # only known_issue_note changed.
    assert leaky_run.rf_r2 == 0.9334544740842177
    assert leaky_run.deployed is True
    assert leaky_run.deployed_model_type == "random_forest"
    assert leaky_run.rejection_reason == ""
    assert leaky_run.error_message == ""
    assert leaky_run.row_count == 888


def test_no_matching_run_is_a_safe_no_op():
    _make_run(rf_r2=0.5, deployed=False, deployed_model_type="")

    assert leaky_msrp_proxy_run_queryset(MLTrainingRun).first() is None
