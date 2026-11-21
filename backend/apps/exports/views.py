import json

from django.conf import settings
from django.http import HttpResponse
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.comparisons.services import ComparisonConfigError, build_comparison
from apps.depreciation.serializers import PathwayTcoSerializer
from apps.depreciation.services import OperatingCostConfigError, build_tco_report
from apps.profiles.models import declared_mileage_band_for, ncd_percent_for, prefers_islamic_financing

from .comparison_rows import build_export_context, build_tco_sections
from .filenames import download_name_from_stored_path, pdf_download_name
from .models import PDFExportFailureReason, PDFExportJob, PDFExportJobStatus
from .pdf import ENGINE_UNAVAILABLE_MESSAGE, TIMEOUT_MESSAGE
from .serializers import PDFExportRequestSerializer
from .tasks import generate_pdf_task

# QA audit C3b: a missing-dependency failure must report as unavailable
# (503), never as a timeout (504) - those are genuinely different
# problems with different honest status codes.
_STATUS_BY_FAILURE_REASON = {
    PDFExportFailureReason.TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
    PDFExportFailureReason.ENGINE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
}
_DEFAULT_MESSAGE_BY_FAILURE_REASON = {
    PDFExportFailureReason.TIMEOUT: TIMEOUT_MESSAGE,
    PDFExportFailureReason.ENGINE_UNAVAILABLE: ENGINE_UNAVAILABLE_MESSAGE,
}


def _as_plain_json(pathway_tco):
    """The pathway TCO as the API sends it (Decimals as 2 dp strings), so it
    survives the Celery task's JSON serialization; None stays None."""
    if pathway_tco is None:
        return None
    return json.loads(json.dumps(PathwayTcoSerializer(pathway_tco).data))


class PDFExportView(APIView):
    """F008 - UC008 PDF Document Export Generation.

    Dispatches generate_pdf_task as a real Celery task (.delay()). With
    CELERY_TASK_ALWAYS_EAGER=True (this dev environment - no Redis, see
    README), the task has already completed by the time .delay() returns,
    so the job's status is checked immediately: a completed PDF streams
    back in this same response; a failed/timed-out job returns UC008's
    exact alt-flow message as 504, never a 500. Once real async execution
    is set up, this endpoint would instead return the job id for a client
    to poll/download separately - the PDFExportJob model already supports
    that without changes.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PDFExportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        vehicle = data["vehicle"]

        # QA audit C4: never print whatever pathway figures the client
        # claims - recompute them the same way every other endpoint does.
        ncd_percent = ncd_percent_for(request.user)
        common = {
            "vehicle": vehicle,
            "tenure_months": data["tenure_months"],
            "mileage_band": data["mileage_band"],
            "downpayment": data["downpayment"],
            # Same NCD as the screen, from the user's own profile.
            "ncd_percent": ncd_percent,
        }
        comparison = build_comparison(**common)
        # Run 1 fix batch 4: the same TCO-for-every-pathway table as the TCO
        # tab. A car the TCO can't be built for still exports - the PDF says why.
        # Run 2 fix batch 1: and the rest of the TCO tab (summary, running costs,
        # factor explanation, risk alerts, contract checklist), formatted
        # server-side from this same report - never from the client.
        pathway_tco, tco_sections, tco_unavailable_reason = None, None, None
        try:
            tco_report = build_tco_report(**common, declared_mileage_band=declared_mileage_band_for(request.user))
            pathway_tco = tco_report["pathway_tco"]
            tco_sections = build_tco_sections(tco_report)
        except (ComparisonConfigError, OperatingCostConfigError) as exc:
            tco_unavailable_reason = str(exc)
        # The user's Islamic-financing preference (a label only: "profit rate" for
        # "interest rate" - no figure changes), read from their own profile.
        export_context = build_export_context(
            comparison, prefers_islamic_financing(request.user),
            pathway_tco=_as_plain_json(pathway_tco), tco_unavailable_reason=tco_unavailable_reason,
            tco_sections=tco_sections,
        )

        job = PDFExportJob.objects.create(user=request.user)
        generate_pdf_task.delay(
            job.pk,
            vehicle_label=f"{vehicle.brand.name} {vehicle.name} {vehicle.trim}",
            export_context=export_context,
            chart_svg=data.get("chart_svg", ""),
            timeout_seconds=settings.PDF_COMPILATION_TIMEOUT_SECONDS,
            download_name=pdf_download_name(vehicle, data["tenure_months"]),
        )

        # Run 1 fix batch 5: with a real worker (eager mode off) the job is
        # still queued here - hand back its id to poll; the PDF is fetched from
        # the download endpoint once it has succeeded.
        if not settings.CELERY_TASK_ALWAYS_EAGER:
            job.refresh_from_db()
            return Response(_job_status_body(job), status=status.HTTP_202_ACCEPTED)

        # Eager mode (dev, the demo): the task already ran inline - stream the
        # PDF back in this same response, exactly as before.
        job.refresh_from_db()
        if job.status == PDFExportJobStatus.SUCCEEDED:
            return _pdf_file_response(job)
        return _failure_response(job)


def _pdf_file_response(job):
    with open(job.file_path, "rb") as pdf_file:
        pdf_bytes = pdf_file.read()
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    # FX-2 (item 13): FlexiDriveMy_{brand}-{model}_{tenure}m_{date}.pdf (older jobs keep their old name).
    response["Content-Disposition"] = f'attachment; filename="{download_name_from_stored_path(job.file_path, job.pk)}"'
    return response


def _failure_response(job):
    # QA audit C3b: an engine-unavailable failure must report as
    # unavailable (503) with an honest message, never as a fabricated
    # timeout (504) - job.failure_reason (set by generate_pdf_task)
    # says which actually happened.
    response_status = _STATUS_BY_FAILURE_REASON.get(job.failure_reason, status.HTTP_504_GATEWAY_TIMEOUT)
    return Response({"detail": _failure_message(job)}, status=response_status)


def _failure_message(job):
    default_message = _DEFAULT_MESSAGE_BY_FAILURE_REASON.get(job.failure_reason, TIMEOUT_MESSAGE)
    return job.error_message or default_message


def _job_status_body(job):
    return {
        "job_id": job.pk,
        "status": job.status,
        "detail": _failure_message(job) if job.status == PDFExportJobStatus.FAILED else None,
    }


class _OwnJobMixin:
    """Another user's job is simply not found (404), never a 403 that would
    confirm it exists."""

    permission_classes = [permissions.IsAuthenticated]

    def get_own_job(self, request, job_id):
        job = PDFExportJob.objects.filter(pk=job_id, user=request.user).first()
        if job is None:
            raise NotFound()
        return job


class PDFExportJobStatusView(_OwnJobMixin, APIView):
    """GET /api/exports/pdf/{job_id}/ - run 1 fix batch 5: a queued export's
    status ({job_id, status, detail}), for the button to poll when a real
    Celery worker runs the task."""

    def get(self, request, job_id):
        return Response(_job_status_body(self.get_own_job(request, job_id)))


class PDFExportJobDownloadView(_OwnJobMixin, APIView):
    """GET /api/exports/pdf/{job_id}/download/ - the finished PDF. A job that
    failed answers with its own message and status (504/503); one still
    pending or running is a 409."""

    def get(self, request, job_id):
        job = self.get_own_job(request, job_id)
        if job.status == PDFExportJobStatus.SUCCEEDED:
            return _pdf_file_response(job)
        if job.status == PDFExportJobStatus.FAILED:
            return _failure_response(job)
        return Response(
            {"detail": "The PDF is still being prepared. Please try again in a moment."},
            status=status.HTTP_409_CONFLICT,
        )
