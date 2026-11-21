from celery import shared_task
from django.utils import timezone

from apps.audit.services import log_runtime_error

from . import paultan_research
from .models import BodySegment, Powertrain, VehicleSpecDraft, VehicleSpecDraftStatus

_ERROR_MESSAGE_MAX = 500

# paultan_research's result attribute -> the draft's existing
# proposed_data/missing_fields key (the real VehicleModel field names).
# engine_power_kw feeds the legacy-named engine_capacity_kw (power output).
_FIELD_MAP = {
    "body_type": "body_segment",
    "model_year": "model_year",
    "msrp": "msrp",
    "engine_power_kw": "engine_capacity_kw",
    "powertrain": "powertrain",
    "engine_capacity_cc": "engine_capacity_cc",
}


def spec_draft_failed_message(exc):
    return (
        f"Couldn't fetch the spec page ({type(exc).__name__}). Please try again, or fill in the form by hand."
    )


def _to_powertrain(value):
    """paultan_research already returns Powertrain values; this only
    guarantees nothing outside the real choices ever reaches the form."""
    return value if value in Powertrain.values else None


def _to_body_segment(body_type):
    """paultan's body type -> one of BodySegment's real choices. paultan
    also has Wagon/Convertible/Commercial, which BodySegment doesn't -
    those are left missing rather than forced onto a near-miss choice."""
    if body_type is None:
        return None
    value = body_type.strip().lower()
    return value if value in BodySegment.values else None


@shared_task
def fetch_vehicle_spec_draft(draft_id):
    """F010 optional stretch goal - renders the admin-chosen variant page
    of paultan.org's Car Buyer's Guide (draft.source_url, already SSRF-
    checked by VehicleSpecDraftCreateSerializer) and stages its specs on
    the draft. Never creates a VehicleModel.

    Outcomes: READY (fields found go into proposed_data, the rest into
    missing_fields - never guessed), NOT_FOUND (the page 404s), or FAILED
    (any other HTTP error status, or any unhandled error - network,
    browser, parsing). FAILED exists so a
    crash can't leave the draft stuck in PENDING with the frontend polling
    blindly; nothing is re-raised (same "terminate cleanly, record why"
    pattern as apps.exports.tasks.generate_pdf_task).
    """
    draft = VehicleSpecDraft.objects.get(pk=draft_id)
    try:
        page = paultan_research.render_research_page(draft.source_url)
        draft.fetched_at = timezone.now()

        if page["status"] == 404:
            draft.status = VehicleSpecDraftStatus.NOT_FOUND
            draft.save(update_fields=["status", "fetched_at", "updated_at"])
            return

        # A 403/5xx page isn't "a page with no data" - extracting from it
        # would end READY with every field missing and hide the real cause.
        if page["status"] is not None and page["status"] >= 400:
            draft.status = VehicleSpecDraftStatus.FAILED
            draft.error_message = f"HTTP {page['status']} from paultan.org"
            draft.save(update_fields=["status", "error_message", "fetched_at", "updated_at"])
            return

        result = paultan_research.extract_variant_spec(draft.source_url, page["title"], page["text"])
        values = {
            "body_type": _to_body_segment(result.body_type),
            "model_year": result.model_year,
            "msrp": result.msrp,
            "engine_power_kw": result.engine_power_kw,
            "powertrain": _to_powertrain(result.powertrain),
            "engine_capacity_cc": result.engine_capacity_cc,
        }
        is_bev = values["powertrain"] == Powertrain.BEV

        proposed_data = {}
        missing_fields = []
        for source_name, draft_field in _FIELD_MAP.items():
            value = values[source_name]
            if source_name == "engine_capacity_cc" and is_bev:
                # A battery electric vehicle has no engine capacity: not
                # "missing", and never proposed (the contract forbids it).
                continue
            if value is None:
                missing_fields.append(draft_field)
            else:
                # JSONField can't hold a Decimal - stringified, same as
                # every other currency/measurement figure on the wire.
                proposed_data[draft_field] = str(value)

        draft.status = VehicleSpecDraftStatus.READY
        draft.proposed_data = proposed_data
        draft.missing_fields = missing_fields
        draft.save(update_fields=["status", "proposed_data", "missing_fields", "fetched_at", "updated_at"])
    except Exception as exc:
        # Run 1 fix batch 4: a distinct FAILED status with a safe, plain
        # message (the error's type only, never its raw text - a browser or
        # network error can carry URLs, paths or headers); the details go to
        # a "runtime_error" audit row and the Python log.
        draft.status = VehicleSpecDraftStatus.FAILED
        draft.error_message = spec_draft_failed_message(exc)[:_ERROR_MESSAGE_MAX]
        draft.fetched_at = timezone.now()
        draft.save(update_fields=["status", "error_message", "fetched_at", "updated_at"])
        log_runtime_error(
            source="spec_draft", error=exc, actor=draft.requested_by, status=None, context={"draft_id": draft.pk},
        )
