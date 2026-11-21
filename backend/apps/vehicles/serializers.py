from decimal import Decimal
from urllib.parse import urlparse

from django.core.validators import MaxValueValidator, MinValueValidator
from rest_framework import serializers

from apps.common.constants import minimum_downpayment_for

from . import paultan_research
from .models import (
    POWERTRAIN_PHRASE,
    ROAD_TAX_CLASS_HELP_TEXT,
    Brand,
    RoadTaxClass,
    VehicleModel,
    VehicleSpecDraft,
    powertrain_spec_errors,
)


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name", "tier_code", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def validate_name(self, value):
        # QA audit L14: same reasoning as H7's email fix - Brand.name's
        # plain unique=True only catches an EXACT-case match, so creating
        # "toyota" when "Toyota" already exists would sail past it and
        # only collide with the DB's case-insensitive UniqueConstraint
        # (migration - see Lower("name")) as an unhandled 500. Checked
        # here first so it's always a clean 400.
        queryset = Brand.objects.filter(name__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A brand with that name already exists.")
        return value


class BlankAsNullIntegerField(serializers.IntegerField):
    """An optional whole number where a blank value ("" from a form, an empty
    spreadsheet cell) means "not given" (null) rather than an error."""

    def validate_empty_values(self, data):
        if isinstance(data, str) and data.strip() == "":
            data = None
        return super().validate_empty_values(data)


# Run 1 fix batch 5 (UC010): the field names the Fleet form shows, for plain
# error messages in place of DRF's generic ones.
VEHICLE_FIELD_LABELS = {
    "brand": "Brand",
    "name": "Model name",
    "trim": "Trim",
    "body_segment": "Body segment",
    "model_year": "Model year",
    "msrp": "MSRP",
    "engine_capacity_kw": "Power output",
    "powertrain": "Powertrain",
    "engine_capacity_cc": "Engine capacity",
    "road_tax_class": "Road-tax class",
    "thumbnail_url": "Thumbnail URL",
}


def _plain_messages(label):
    return {
        "required": f"{label} is required.",
        "null": f"{label} is required.",
        "blank": f"{label} is required.",
        "invalid_choice": f"Choose a {label[0].lower()}{label[1:]}.",
    }


class VehicleModelSerializer(serializers.ModelSerializer):
    """Used for single-entry CRUD and, row-by-row, for bulk CSV/Excel import
    (UC010's alternate flow) — both paths validate against this same schema."""

    brand_name = serializers.CharField(source="brand.name", read_only=True)
    # Run 1 fix batch 5 (D1): optional - blank or missing is stored as null on
    # every path (form, bulk import, spec draft), never an invented year.
    model_year = BlankAsNullIntegerField(required=False, allow_null=True, min_value=1900, max_value=2100)
    # Computed in Python (the project spec's non-negotiable rule: money math
    # never happens in TypeScript) - 10% of msrp, rounded up to the cent.
    # The frontend defaults the downpayment input to this and only
    # *compares* against it client-side, never re-derives it.
    min_downpayment = serializers.SerializerMethodField()
    # Declared explicitly (rather than left to ModelSerializer's auto min/max
    # kwargs) so the exact messages from UC010's alt flow reach the API
    # response instead of DRF's generic "Ensure this value is..." text.
    msrp = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.01"), message="MSRP must be a positive numeric value."),
            # QA audit L11 - see apps.vehicles.models.VehicleModel.msrp's
            # own comment for why RM100,000,000.00.
            MaxValueValidator(
                Decimal("100000000.00"), message="MSRP must be between RM0.01 and RM100,000,000.00."
            ),
        ],
    )
    # Legacy name, power output in kW - see VehicleModel.engine_capacity_kw.
    engine_capacity_kw = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[
            # QA audit L13 - raised from 500.00 to 700.00 kW; see
            # apps.vehicles.models.VehicleModel.engine_capacity_kw's own
            # comment for why (BMW M5/Porsche Taycan Turbo S real trims).
            MinValueValidator(Decimal("0.10"), message="Power output must be between 0.10 kW and 700.00 kW."),
            MaxValueValidator(Decimal("700.00"), message="Power output must be between 0.10 kW and 700.00 kW."),
        ],
    )
    # Declared explicitly for the same reason as msrp above: DRF's auto-built
    # field would drop the validators' custom messages.
    engine_capacity_cc = serializers.IntegerField(
        required=False,
        allow_null=True,
        validators=[
            MinValueValidator(600, message="Engine capacity must be between 600 cc and 8,000 cc."),
            MaxValueValidator(8000, message="Engine capacity must be between 600 cc and 8,000 cc."),
        ],
    )
    # Run 1 fix batch 3: the JPJ registration class (saloon / non-saloon).
    # Optional on every write path (form, bulk import, spec draft): blank or
    # omitted means "the body type's default", filled by VehicleModel.save().
    road_tax_class = serializers.ChoiceField(
        choices=RoadTaxClass.choices, required=False, allow_blank=True, help_text=ROAD_TAX_CLASS_HELP_TEXT
    )
    # False when the class was set to something other than the body type's
    # default - Vehicle Readiness asks for a check against the VOC.
    road_tax_class_is_default = serializers.BooleanField(read_only=True)
    # True once the new-vehicle contract holds (powertrain set; cc present
    # unless BEV). False flags a legacy row as "Needs specs" in the Fleet UI.
    spec_complete = serializers.BooleanField(read_only=True)
    # Run 1 fix batch 5 (A4): "mild hybrid", "electric"... - the same phrase the
    # running-cost and residual basis lines use; "" when no powertrain is set.
    powertrain_phrase = serializers.SerializerMethodField()

    class Meta:
        model = VehicleModel
        fields = [
            "id",
            "brand",
            "brand_name",
            "name",
            "trim",
            "body_segment",
            "model_year",
            "msrp",
            "min_downpayment",
            "engine_capacity_kw",
            "powertrain",
            "powertrain_phrase",
            "engine_capacity_cc",
            "road_tax_class",
            "road_tax_class_is_default",
            "spec_complete",
            "thumbnail_url",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Run 1 fix batch 5 (UC010): "Brand is required." / "Choose a body
        # segment." instead of DRF's "This field may not be null." / '"" is
        # not a valid choice.'. Field-specific messages (e.g. "MSRP must be a
        # positive numeric value.") are validator messages and stay as they are.
        for name, label in VEHICLE_FIELD_LABELS.items():
            field = self.fields.get(name)
            if field is not None and not field.read_only:
                field.error_messages.update(_plain_messages(label))

    def get_min_downpayment(self, obj) -> str:
        return str(minimum_downpayment_for(obj.msrp))

    def get_powertrain_phrase(self, obj) -> str:
        return POWERTRAIN_PHRASE.get(obj.powertrain, "")

    def validate(self, attrs):
        # The new-vehicle contract (see powertrain_spec_errors). For an
        # update, whatever the request doesn't send falls back to the
        # stored value, so a PATCH is judged on the row's effective specs.
        instance = self.instance
        powertrain = attrs["powertrain"] if "powertrain" in attrs else getattr(instance, "powertrain", "")
        cc = attrs["engine_capacity_cc"] if "engine_capacity_cc" in attrs else getattr(
            instance, "engine_capacity_cc", None
        )
        errors = powertrain_spec_errors(powertrain, cc)
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def validate_brand(self, value):
        # Same rule as apps.policy.serializers.ActiveBrandOnlyMixin: editing
        # a vehicle may keep its OWN brand after that brand was archived
        # (AdminFleetPage keeps it selectable), but creating one under an
        # archived brand - including bulk import, which never passes an
        # instance - or switching to a different archived brand is rejected.
        keeping_own_brand = self.instance is not None and self.instance.brand_id == value.pk
        if not value.is_active and not keeping_own_brand:
            raise serializers.ValidationError("Brand is archived and cannot be assigned to new vehicles.")
        return value


class VehicleSpecDraftCreateSerializer(serializers.ModelSerializer):
    """F010 optional stretch - the variant the admin picked from
    paultan.org's buyer's guide listings. `source_url` is the one URL the
    background task will fetch, so it is validated here as an SSRF guard:
    only an https://paultan.org/research/<brand>/<model>/<gen>/<variant>-
    <year>/ page is accepted. model_name_query/trim_query are display text
    only (and pre-fill Name/Trim); everything the fetch produces is
    written by the Celery task alone."""

    class Meta:
        model = VehicleSpecDraft
        fields = ["id", "brand", "source_url", "model_name_query", "trim_query", "status"]
        read_only_fields = ["id", "status"]
        extra_kwargs = {
            "source_url": {"required": True, "allow_blank": False},
            "model_name_query": {"required": False, "allow_blank": True},
        }

    def validate_source_url(self, value):
        if not (paultan_research.is_allowed_research_url(value) and paultan_research.is_variant_url(value)):
            raise serializers.ValidationError(
                "Must be a paultan.org Car Buyer's Guide variant page "
                "(https://paultan.org/research/<brand>/<model>/<generation>/<variant>-<year>/)."
            )
        return value

    def validate(self, attrs):
        # validate_source_url already guaranteed /research/<brand>/<model>/...
        _research, url_brand, url_model, *_rest = urlparse(attrs["source_url"]).path.strip("/").split("/")
        # The page must belong to the brand the draft is filed under -
        # otherwise a BMW draft could silently pre-fill Porsche specs.
        if url_brand != paultan_research.brand_slug(attrs["brand"].name):
            raise serializers.ValidationError(
                {"source_url": f"This page is not a {attrs['brand'].name} variant."}
            )
        if not attrs.get("model_name_query"):
            attrs["model_name_query"] = url_model.replace("-", " ").title()
        return attrs


class VehicleSpecDraftSerializer(serializers.ModelSerializer):
    """F010 optional stretch - read shape (GET, used for polling) and the
    one allowed write path after creation: PATCH status/approved_vehicle,
    which the frontend fires (fire-and-forget) only after the admin's own
    VehicleModelViewSet.create() call already succeeded - traceability
    only, per VehicleSpecDraft's own docstring."""

    brand_name = serializers.CharField(source="brand.name", read_only=True)

    class Meta:
        model = VehicleSpecDraft
        fields = [
            "id",
            "brand",
            "brand_name",
            "model_name_query",
            "trim_query",
            "status",
            "source_url",
            "proposed_data",
            "missing_fields",
            "fetched_at",
            "error_message",
            "approved_vehicle",
            "requested_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "brand",
            "brand_name",
            "model_name_query",
            "trim_query",
            "source_url",
            "proposed_data",
            "missing_fields",
            "fetched_at",
            "error_message",
            "requested_by",
            "created_at",
            "updated_at",
        ]
