from django.urls import path

from .views import PDFExportJobDownloadView, PDFExportJobStatusView, PDFExportView

urlpatterns = [
    path("pdf/", PDFExportView.as_view(), name="pdf-export"),
    # Run 1 fix batch 5: used only when a real Celery worker runs the export
    # (CELERY_TASK_ALWAYS_EAGER=False) - poll, then download.
    path("pdf/<int:job_id>/", PDFExportJobStatusView.as_view(), name="pdf-export-status"),
    path("pdf/<int:job_id>/download/", PDFExportJobDownloadView.as_view(), name="pdf-export-download"),
]
