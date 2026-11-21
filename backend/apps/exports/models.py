from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class PDFExportJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class PDFExportFailureReason(models.TextChoices):
    """Distinguishes WHY a job failed (QA audit C3b: a missing-dependency
    failure was previously always reported to the client as a generation
    timeout, which is simply false) - lets the view pick an honest status
    code/message per failure kind instead of a single blanket 504."""

    TIMEOUT = "timeout", "Timeout"
    ENGINE_UNAVAILABLE = "engine_unavailable", "Rendering engine unavailable"


class PDFExportJob(TimeStampedModel):
    """F008 - UC008 PDF Document Export Generation. Tracks one compile
    attempt so the endpoint can work both in eager Celery mode (check the
    job immediately after dispatch, stream the result) and in real async
    mode later (a client polls this job's status/file)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="pdf_export_jobs"
    )
    status = models.CharField(max_length=20, choices=PDFExportJobStatus.choices, default=PDFExportJobStatus.PENDING)
    file_path = models.CharField(max_length=500, blank=True)
    error_message = models.TextField(blank=True)
    failure_reason = models.CharField(
        max_length=20, choices=PDFExportFailureReason.choices, blank=True
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"PDF export job #{self.pk} ({self.status})"
