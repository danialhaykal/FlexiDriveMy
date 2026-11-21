import hashlib
import logging

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.mixins import AuditedModelViewSet
from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.common.error_messages import plain_error_messages
from apps.common.query_params import parse_decimal_param, parse_int_param
from apps.users.permissions import IsAdminRole

from . import archiving, paultan_research, readiness
from .imports import StructuralImportError, normalize_row, parse_upload
from .models import BodySegment, Brand, VehicleModel, VehicleSpecDraft
from .serializers import (
    BrandSerializer,
    VehicleModelSerializer,
    VehicleSpecDraftCreateSerializer,
    VehicleSpecDraftSerializer,
)
from .tasks import fetch_vehicle_spec_draft

logger = logging.getLogger(__name__)

# paultan's buyer's-guide listings change on the order of weeks - 12h keeps
# repeat lookups instant without hammering the site.
RESEARCH_LISTING_CACHE_SECONDS = 12 * 60 * 60
RESEARCH_UNAVAILABLE_MESSAGE = "Could not reach paultan.org right now. Please try again shortly."


def _cacheable_listing(page, items):
    """A real listing, or a real 404, is worth 12h. An EMPTY listing from any
    other page (a bot check, an error page, a layout change) may be a passing
    blip, so it's never cached - the next request tries again."""
    return bool(items) or page["status"] == 404


class CascadingArchiveViewSetMixin:
    """DELETE/unarchive cascade through apps.vehicles.archiving, and
    GET .../<id>/archive-impact/ previews what they would change."""

    archive = restore = None  # set per subclass

    def perform_archive(self, instance):
        type(self).archive(instance, actor=self.request.user, request=self.request)

    def perform_unarchive(self, instance):
        plan = type(self).restore(instance, actor=self.request.user, request=self.request)
        return {"cascade": plan.as_dict()}

    @action(detail=True, methods=["get"], url_path="archive-impact")
    def archive_impact(self, request, pk=None):
        # Archived rows included, same bypass as destroy()/unarchive().
        instance = self.queryset.model.objects.filter(pk=pk).first()
        if instance is None:
            raise NotFound()
        return Response(archiving.impact(instance))


class BrandViewSet(CascadingArchiveViewSetMixin, AuditedModelViewSet, viewsets.ModelViewSet):
    """F010 - brand records backing the fleet (CRUD + archive). Archiving a
    brand cascades to its vehicles and policy rows (apps.vehicles.archiving)."""

    resource_type = "vehicles.Brand"
    serializer_class = BrandSerializer
    permission_classes = [IsAdminRole]
    queryset = Brand.objects.all()
    archive = staticmethod(archiving.archive_brand)
    restore = staticmethod(archiving.restore_brand)


class VehicleModelViewSet(CascadingArchiveViewSetMixin, AuditedModelViewSet, viewsets.ModelViewSet):
    """F010 - UC010 Fleet & Car Specification Management.

    Single-record CRUD (main flow) plus a bulk-import action (alternate
    flow) that validates every spreadsheet row against this same
    VehicleModelSerializer, reports row-level errors, and commits only the
    valid rows in one transaction.
    """

    resource_type = "vehicles.VehicleModel"
    serializer_class = VehicleModelSerializer
    permission_classes = [IsAdminRole]
    queryset = VehicleModel.objects.select_related("brand").all()
    archive = staticmethod(archiving.archive_vehicle)
    restore = staticmethod(archiving.restore_vehicle)

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser])
    def bulk_import(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "No file uploaded."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            rows = parse_upload(uploaded_file)
        except StructuralImportError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # QA audit M2: a header-only file (no data rows) previously
        # returned a silent 200 with everything at zero - indistinguishable
        # from "nothing needed importing" vs. "you probably uploaded the
        # wrong file".
        if not rows:
            return Response(
                {"detail": "The uploaded file has no data rows to import."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        errors = []
        to_create = []  # list of (row_number, validated_data)
        seen_keys = set()  # (brand_id, name, trim) already queued in THIS batch

        for row_number, row in enumerate(rows, start=2):  # row 1 is the header
            data, row_error = normalize_row(row)
            if row_error:
                errors.append({"row": row_number, "errors": row_error})
                continue
            serializer = VehicleModelSerializer(data=data)
            if not serializer.is_valid():
                # Run 2 fix batch 3: the same plain number/choice wording as a
                # single-entry form (this report is built by hand, so it doesn't
                # pass through the API exception handler).
                errors.append({"row": row_number, "errors": plain_error_messages(serializer.errors)})
                continue

            validated = serializer.validated_data
            key = (validated["brand"].pk, validated["name"], validated["trim"])
            if key in seen_keys:
                # QA audit M2: two rows in the SAME upload, neither of
                # which exists in the DB yet, each pass is_valid() on
                # their own (nothing to collide with at validation time)
                # and only collided at .create() - a raw IntegrityError
                # inside the atomic block below, previously uncaught,
                # which rolled back AND lost every earlier row in this
                # same batch with no report of why. Caught here instead,
                # as a normal per-row error, before any row is created.
                errors.append(
                    {
                        "row": row_number,
                        "errors": {
                            "trim": [
                                "This brand/name/trim combination is duplicated elsewhere in this file."
                            ]
                        },
                    }
                )
                continue
            seen_keys.add(key)
            to_create.append((row_number, validated))

        created_instances = []
        with transaction.atomic():
            for row_number, validated_data in to_create:
                instance = VehicleModel.objects.create(**validated_data)
                created_instances.append(instance)
                write_audit_log(
                    actor=request.user,
                    request=request,
                    action=AuditActionCategory.BULK_IMPORT,
                    resource_type=self.resource_type,
                    resource_id=instance.pk,
                    before=None,
                    after=self.get_serializer(instance).data,
                )

        return Response(
            {
                "total_rows": len(rows),
                "created_count": len(created_instances),
                "error_count": len(errors),
                "errors": errors,
                "created": self.get_serializer(created_instances, many=True).data,
            },
            status=status.HTTP_200_OK,
        )


class CatalogVehicleViewSet(viewsets.ReadOnlyModelViewSet):
    """F004 - UC004 Catalog Browse & Search.

    Read-only and open to any authenticated user (not just admins) - unlike
    VehicleModelViewSet, this always scopes to is_active=True with no
    ?include_archived escape hatch (UC004 Rule 1: only active/published
    vehicles are ever visible here).
    """

    serializer_class = VehicleModelSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = VehicleModel.objects.select_related("brand").visible()

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        # QA audit M1: every value below is validated/parsed before it
        # ever reaches a queryset filter - a bad raw string (non-numeric
        # brand/min_price/max_price, an unrecognized body_segment) used
        # to only fail once the queryset was actually evaluated, as an
        # unhandled 500 deep in query execution.
        brand = params.get("brand")
        if brand:
            brand_id = parse_int_param(params, "brand")
            if not Brand.objects.filter(pk=brand_id).exists():
                raise ValidationError({"brand": f"No brand with id {brand_id}."})
            queryset = queryset.filter(brand_id=brand_id)

        body_segment = params.get("body_segment")
        if body_segment:
            if body_segment not in BodySegment.values:
                raise ValidationError(
                    {"body_segment": f"Must be one of: {', '.join(BodySegment.values)}."}
                )
            queryset = queryset.filter(body_segment=body_segment)

        min_price = parse_decimal_param(params, "min_price")
        max_price = parse_decimal_param(params, "max_price")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValidationError({"min_price": "min_price must not be greater than max_price."})
        if min_price is not None:
            queryset = queryset.filter(msrp__gte=min_price)
        if max_price is not None:
            queryset = queryset.filter(msrp__lte=max_price)

        search = params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(trim__icontains=search) | Q(brand__name__icontains=search)
            )

        return queryset

    @action(detail=False, methods=["get"])
    def brands(self, request):
        """Active brands for populating the catalog's brand filter (any
        authenticated user - unlike BrandViewSet, which is admin-only)."""
        brands = Brand.objects.filter(is_active=True).order_by("name")
        return Response(BrandSerializer(brands, many=True).data)


class VehicleSpecDraftViewSet(viewsets.ModelViewSet):
    """F010 optional stretch goal - UC010's 'Fetch Spec Draft' assist
    staging resource. Admin-only, like every other admin write surface in
    this app. Deliberately NOT an AuditedModelViewSet - this staging row
    is never F013-reportable admin data itself; the actual VehicleModel
    this eventually feeds still goes through VehicleModelViewSet's own
    existing, unchanged audit logging.

    POST creates the draft and dispatches the fetch as a background
    Celery task (never run inline in this request) - the response
    returns immediately with the new draft's id/status=pending, so the
    frontend can start polling GET .../<id>/ right away.
    """

    permission_classes = [IsAdminRole]
    queryset = VehicleSpecDraft.objects.select_related("brand").all()

    def get_serializer_class(self):
        if self.action == "create":
            return VehicleSpecDraftCreateSerializer
        return VehicleSpecDraftSerializer

    def perform_create(self, serializer):
        draft = serializer.save(requested_by=self.request.user)
        fetch_vehicle_spec_draft.delay(draft.pk)

    @action(detail=False, methods=["get"], url_path="catalog-models")
    def catalog_models(self, request):
        """Step 1 of the picker: every model on paultan's buyer's-guide
        brand page, e.g. ?brand=BMW -> /research/bmw/."""
        brand_name = (request.query_params.get("brand") or "").strip()
        if not brand_name:
            return Response({"brand": "This query parameter is required."}, status=status.HTTP_400_BAD_REQUEST)

        slug = paultan_research.brand_slug(brand_name)
        cache_key = f"paultan-research:models:{slug}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            page = paultan_research.render_research_page(paultan_research.brand_page_url(brand_name))
        except Exception:
            logger.exception("catalog_models: rendering the paultan brand page failed for %r", slug)
            return Response({"detail": RESEARCH_UNAVAILABLE_MESSAGE}, status=status.HTTP_502_BAD_GATEWAY)

        models = [] if page["status"] == 404 else paultan_research.parse_model_links(page["links"], slug)
        payload = {"brand_slug": slug, "models": models}
        if not models:
            payload["message"] = "No paultan.org buyer's-guide page for this brand"
        if _cacheable_listing(page, models):
            cache.set(cache_key, payload, RESEARCH_LISTING_CACHE_SECONDS)
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="catalog-variants")
    def catalog_variants(self, request):
        """Step 2 of the picker: every variant on one model page. The
        model_url is client-supplied, so it's SSRF-checked before any
        fetch - only https://paultan.org/research/<brand>/<model>/."""
        model_url = (request.query_params.get("model_url") or "").strip()
        slugs = paultan_research.model_slug_from_url(model_url)
        if not (paultan_research.is_allowed_research_url(model_url) and slugs):
            return Response(
                {"model_url": "Must be a paultan.org Car Buyer's Guide model page."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache_key = f"paultan-research:variants:{hashlib.sha256(model_url.encode()).hexdigest()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            page = paultan_research.render_research_page(model_url)
        except Exception:
            logger.exception("catalog_variants: rendering the paultan model page failed for %r", model_url)
            return Response({"detail": RESEARCH_UNAVAILABLE_MESSAGE}, status=status.HTTP_502_BAD_GATEWAY)

        variants = [] if page["status"] == 404 else paultan_research.parse_variant_links(page["links"], *slugs)
        payload = {"variants": variants}
        if not variants:
            payload["message"] = "No variants listed for this model on paultan.org"
        if _cacheable_listing(page, variants):
            cache.set(cache_key, payload, RESEARCH_LISTING_CACHE_SECONDS)
        return Response(payload)

class VehicleReadinessView(APIView):
    """Admin, read-only: for every active vehicle, whether the app can fully
    price it - each check calls the same code the screens use (see
    apps.vehicles.readiness), so a new rule appears here automatically.
    Returns {"results": [...]}; each result has an overall status ("ready" or
    "needs_attention"), counts, and its list of checks."""

    permission_classes = [IsAdminRole]

    def get(self, request):
        return Response({"results": readiness.readiness_report()})
