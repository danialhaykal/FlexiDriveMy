"""F008 - persists generated PDF files, mirroring apps/ml/storage.py's
pattern (a new uniquely-named file per job, not a fixed filename)."""

import uuid
from pathlib import Path

from django.conf import settings


def pdf_storage_dir():
    path = Path(settings.PDF_EXPORTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_pdf(pdf_bytes, job_id, download_name=None):
    # FX-2 (item 13): the download name rides in the stored file's own name, after "__"
    # (exports.filenames.download_name_from_stored_path reads it back) - no extra field.
    filename = f"export_{job_id}_{uuid.uuid4().hex[:8]}.pdf"
    if download_name:
        filename = f"export_{job_id}_{uuid.uuid4().hex[:8]}__{download_name}"
    file_path = pdf_storage_dir() / filename
    file_path.write_bytes(pdf_bytes)
    return str(file_path)
