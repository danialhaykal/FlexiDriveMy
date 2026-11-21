from celery import shared_task

from apps.audit.services import log_runtime_error

from .models import PDFExportFailureReason, PDFExportJob, PDFExportJobStatus
from .pdf import PDFCompilationError, PDFCompilationTimeoutError, render_pdf_with_timeout
from .rendering import build_report_html
from .storage import save_pdf


@shared_task
def generate_pdf_task(job_id, *, vehicle_label, export_context, chart_svg, timeout_seconds, download_name=None):
    """F008 - UC008 main flow step 2, run as a Celery background task.

    `export_context` is apps.exports.comparison_rows.build_export_context's
    own return value (pathways plus tenure/downpayment/mileage band/
    generated-at - QA audit M16) - plain str/int/list/dict values only,
    so it survives Celery's JSON task serialization without changes.

    Unlike F012's training task, this does NOT re-raise on failure: UC008's
    alt flow explicitly wants the failure caught and the routine
    "terminated cleanly" (job marked FAILED, error recorded) rather than
    propagated as an unhandled exception - the view checks job.status
    afterward rather than needing to catch anything itself.
    """
    job = PDFExportJob.objects.get(pk=job_id)
    job.status = PDFExportJobStatus.RUNNING
    job.save(update_fields=["status"])

    try:
        html_string = build_report_html(vehicle_label=vehicle_label, chart_svg=chart_svg, **export_context)
        pdf_bytes = render_pdf_with_timeout(html_string, timeout_seconds)
        job.file_path = save_pdf(pdf_bytes, job.pk, download_name=download_name)
        job.status = PDFExportJobStatus.SUCCEEDED
        job.save()
    except PDFCompilationError as exc:
        job.status = PDFExportJobStatus.FAILED
        job.error_message = str(exc)
        is_timeout = isinstance(exc, PDFCompilationTimeoutError)
        job.failure_reason = (
            PDFExportFailureReason.TIMEOUT if is_timeout else PDFExportFailureReason.ENGINE_UNAVAILABLE
        )
        job.save()
        # Run 1 fix batch 4 (UC013): a failed export is a runtime error. The
        # status is what the buyer gets (504 timeout / 503 engine unavailable).
        log_runtime_error(
            source="pdf_export", error=exc, actor=job.user, status=504 if is_timeout else 503,
            context={"job_id": job.pk, "failure_reason": job.failure_reason},
        )
