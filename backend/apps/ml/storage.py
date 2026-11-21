"""F012 - persists/loads trained model files. 'Hot-swapping' the
production model means writing a new uniquely-named file and repointing
ProductionModel at it (see apps/ml/models.py) - never overwriting a fixed
filename in place, which would risk corrupting a file mid-read."""

import uuid
from pathlib import Path

import joblib
from django.conf import settings


def model_storage_dir():
    path = Path(settings.ML_MODELS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_model(estimator, training_run_id, model_type):
    filename = f"model_{training_run_id}_{model_type}_{uuid.uuid4().hex[:8]}.joblib"
    file_path = model_storage_dir() / filename
    joblib.dump(estimator, file_path)
    return str(file_path)


def load_model(file_path):
    return joblib.load(file_path)
