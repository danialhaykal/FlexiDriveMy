"""Plain, importable helpers backing one-off data migrations for
apps/ml/models.py::MLTrainingRun.

Kept separate from the migration files themselves - a migration module's
filename starts with a digit (e.g. 0004_annotate_leaky_msrp_proxy_run.py)
so it can't be imported by a normal `import` statement - so this logic
stays directly unit-testable (see apps/ml/tests/test_data_fixes.py)
without needing to load migration files or replay the migration graph.
"""

# Sprint 13 addendum - the one confirmed pre-fix, leaky msrp_proxy retrain.
#
# Proven by reproduction, not guessed: refitting today's leak-safe
# pipeline with this run's exact RandomForest hyperparameters (max_depth=8,
# n_estimators=100) on the current dataset reproduces the *next* run's R2
# (0.8920) exactly, and does not reproduce this run's own recorded R2
# (0.9335) - today's leak-safe code is structurally incapable of producing
# this run's number, so it must have come from the since-replaced leaky
# msrp_proxy computation (apps/ml/management/commands/build_real_ml_dataset.py's
# compute_msrp_proxy, before its leave-one-out fix).
#
# Run 3 fix batch 5 (F-26): the note is shown on the ML page, so it is worded
# without internal names (it used to name the msrp_proxy feature and its
# leave-one-out fix); clean_ml_run_texts rewords a row stored with the old text.
KNOWN_ISSUE_NOTE_LEAKY_MSRP_PROXY_RUN = (
    "This run's stand-in for the new price was built from each listing's own resale price, so the price "
    "leaked into its own prediction and inflated R². The bug was fixed before the next run; this run's R² "
    "should not be cited as a valid result."
)

LEAKY_RUN_DATASET_FILENAME = "real_historical_pricing.csv"
LEAKY_RUN_RF_R2_MIN = 0.9334
LEAKY_RUN_RF_R2_MAX = 0.9336


def leaky_msrp_proxy_run_queryset(model):
    """`model` is MLTrainingRun - either the real current model class, or
    the historical snapshot a RunPython migration receives via
    apps.get_model(). Matched by its recorded metrics rather than a
    hardcoded row id, since ids can differ across independently-seeded
    environments - and correctly matches nothing in an environment with no
    seeded ML training history (a fresh install, a test database), which
    callers must treat as a safe no-op, not an error.
    """
    return model.objects.filter(
        dataset_filename=LEAKY_RUN_DATASET_FILENAME,
        deployed=True,
        deployed_model_type="random_forest",
        rf_r2__gte=LEAKY_RUN_RF_R2_MIN,
        rf_r2__lte=LEAKY_RUN_RF_R2_MAX,
    )
