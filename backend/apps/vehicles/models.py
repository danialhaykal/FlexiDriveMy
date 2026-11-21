from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower

from apps.common.models import TimeStampedModel


class BrandTier(models.TextChoices):
    """QA audit M15: tier_code was free text - blank, "A", "9", and "nan"
    were all previously accepted, and a "nan" tier fed the ML model a
    NaN feature value and predicted anyway, never setting the degraded
    flag (float("nan") parses without raising - see
    apps.depreciation.inference._resolve_brand_tier_code's explicit
    math.isnan() guard, added as defense in depth alongside this).
    Matches the real, data-driven 1-5 price tier scheme in
    apps/ml/data/README_real_data.md (tier 1 = highest median resale
    price .. tier 5 = lowest) - the only values a trained model's
    brand_code feature can actually mean.
    """

    TIER_1 = "1", "Tier 1 (highest resale value)"
    TIER_2 = "2", "Tier 2"
    TIER_3 = "3", "Tier 3"
    TIER_4 = "4", "Tier 4"
    TIER_5 = "5", "Tier 5 (lowest resale value)"


class Brand(TimeStampedModel):
    """A car brand/manufacturer (e.g. Proton, Honda). Admin-managed."""

    # QA audit L14: plain unique=True only catches an EXACT-case match -
    # same gap H7 fixed for User.email - see the Lower("name")
    # UniqueConstraint below (the real, DB-level guarantee) and
    # BrandSerializer.validate_name (the clean-400 check before that
    # constraint would ever be hit in the normal request path).
    name = models.CharField(max_length=100, unique=True)
    # Feature used by the ML depreciation model (see the project spec). Blank is
    # an explicit, legitimate "no tier assigned yet" state (e.g. a brand
    # with no real training data to base one on) - apps.depreciation.
    # inference.py already treats a blank tier_code as "degrade to the
    # straight-line fallback", never as a value to guess.
    tier_code = models.CharField(max_length=20, blank=True, choices=BrandTier.choices)
    is_active = models.BooleanField(default=True)  # soft delete flag

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="unique_lower_brand_name"),
        ]

    def __str__(self):
        return self.name


class BodySegment(models.TextChoices):
    SEDAN = "sedan", "Sedan"
    HATCHBACK = "hatchback", "Hatchback"
    SUV = "suv", "SUV"
    MPV = "mpv", "MPV"
    PICKUP = "pickup", "Pickup Truck"
    COUPE = "coupe", "Coupe"
    CROSSOVER = "crossover", "Crossover"
    VAN = "van", "Van"


class Powertrain(models.TextChoices):
    """How the car is powered - decides which road-tax scale applies (JPJ
    taxes petrol/diesel/hybrid/PHEV by engine displacement in cc, and BEVs
    by motor kW on a separate scale)."""

    PETROL = "petrol", "Petrol"
    DIESEL = "diesel", "Diesel"
    MILD_HYBRID = "mild_hybrid", "Mild hybrid (MHEV)"
    HYBRID = "hybrid", "Hybrid (HEV)"
    PHEV = "phev", "Plug-in hybrid (PHEV)"
    BEV = "bev", "Battery electric (BEV)"


# Short, lower-case powertrain names for plain-English lines: the running-cost
# and residual basis lines, and the catalog cards (run 1 fix batch 5) - one
# list, so every screen says it the same way.
POWERTRAIN_PHRASE = {
    Powertrain.PETROL: "petrol",
    Powertrain.DIESEL: "diesel",
    Powertrain.MILD_HYBRID: "mild hybrid",
    Powertrain.HYBRID: "hybrid",
    Powertrain.PHEV: "plug-in hybrid",
    Powertrain.BEV: "electric",
}


class RoadTaxClass(models.TextChoices):
    """JPJ registration class, which decides the cc road-tax table: saloon or
    non-saloon (SUV, MPV, pick-up...). Petrol and diesel use the same tables;
    battery electric cars use the kW groups, which are not split by class."""

    SALOON = "saloon", "Saloon"
    NON_SALOON = "non_saloon", "Non-saloon"


ROAD_TAX_CLASS_HELP_TEXT = "Use the class on the car's registration card (VOC). Body type is only the default."

# The default class for each body type. The registration card (VOC) is what
# counts, so an admin may override it; crossovers in particular vary.
ROAD_TAX_CLASS_BY_BODY_SEGMENT = {
    "sedan": RoadTaxClass.SALOON,
    "hatchback": RoadTaxClass.SALOON,
    "coupe": RoadTaxClass.SALOON,
    "suv": RoadTaxClass.NON_SALOON,
    "mpv": RoadTaxClass.NON_SALOON,
    "pickup": RoadTaxClass.NON_SALOON,
    "van": RoadTaxClass.NON_SALOON,
    "crossover": RoadTaxClass.NON_SALOON,
}


def default_road_tax_class(body_segment):
    """The class a car of this body type is usually registered under, or ""
    for an unknown body type (the body_segment choice check reports that)."""
    return ROAD_TAX_CLASS_BY_BODY_SEGMENT.get(body_segment, "")


def powertrain_spec_errors(powertrain, engine_capacity_cc):
    """The new-vehicle contract's cross-field rule (see the project spec), shared by
    VehicleModel.clean() (Django admin), VehicleModelSerializer (API, bulk
    import) and spec_complete so they can never disagree:

      - powertrain is required
      - engine_capacity_cc is required for every powertrain except BEV,
        and must be empty for BEV (an electric motor has no displacement)

    Returns {field: message}; empty when the specs are complete.
    """
    if not powertrain:
        return {"powertrain": "Powertrain is required."}
    if powertrain == Powertrain.BEV:
        if engine_capacity_cc is not None:
            return {
                "engine_capacity_cc": "A battery electric vehicle has no engine capacity - leave this empty."
            }
    elif engine_capacity_cc is None:
        return {
            "engine_capacity_cc": (
                "Engine capacity (cc) is required for every powertrain except battery electric."
            )
        }
    return {}


class VehicleModelQuerySet(models.QuerySet):
    def visible(self):
        """Both the vehicle AND its own brand must be active. QA audit
        H13: every customer-facing endpoint (catalog, comparisons,
        scoring, TCO, scenarios) that used to filter only this model's
        own is_active left an archived brand's vehicles still visible
        and still comparable - the brand filter disagreed with what was
        actually shown. Use this instead of a bare is_active=True filter
        anywhere a vehicle needs to be genuinely customer-visible.
        """
        return self.filter(is_active=True, brand__is_active=True)


class VehicleModel(TimeStampedModel):
    """A specific model/trim under a Brand (e.g. Honda City V). Admin-managed.

    Fields mirror UC010's main-flow input list: brand, model name, trim,
    body segment, MSRP, engine, thumbnail URL. UC010's single "engine
    capacity" is split into three honest fields: power output in kW
    (engine_capacity_kw - legacy name, see below), engine displacement in cc
    (engine_capacity_cc) and the powertrain type. model_year predates UC010
    and stays optional so it doesn't force a value the use case never asked
    for.

    The new-vehicle contract (powertrain required; cc required except for
    BEV, empty for BEV) is enforced in the serializer, in clean() and - for
    the one part old rows can't violate - a DB CheckConstraint. The columns
    stay nullable so rows entered before this existed still load; they read
    as spec_complete=False and are never silently guessed.
    """

    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="models")
    name = models.CharField(max_length=150)
    trim = models.CharField(max_length=100)
    body_segment = models.CharField(max_length=20, choices=BodySegment.choices)
    model_year = models.PositiveIntegerField(null=True, blank=True)
    # QA audit L11: msrp had no upper bound at all - an MSRP at or past
    # ~RM4.26 billion (2^32-1) crashed with an unhandled 500 somewhere
    # downstream that does 32-bit integer math on it, rather than a clean
    # 400 at input validation. RM100 million is comfortably above any
    # real car price (even a hypercar/custom build rarely exceeds a few
    # million RM) while leaving a huge margin under the actual overflow
    # boundary - a sanity ceiling, not a realistic price limit to approach.
    msrp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.01"), message="MSRP must be a positive numeric value."),
            MaxValueValidator(
                Decimal("100000000.00"), message="MSRP must be between RM0.01 and RM100,000,000.00."
            ),
        ],
    )
    # QA audit L13: 500.00 kW excluded real in-scope cars - a BMW M5
    # (535kW) and some Porsche Taycan Turbo S trims (up to ~560kW) would
    # both be rejected outright. Raised to 700.00 kW, comfortably above
    # both with real margin, while the project spec's locked catalog (BMW/
    # Mercedes-Benz/Lexus/Porsche/Toyota, no hypercar brands) means
    # nothing currently in scope approaches even the OLD ceiling, let
    # alone this one.
    # LEGACY NAME: this holds POWER OUTPUT in kW, not engine capacity. It is
    # not renamed because the project spec's ML feature vector lists it as
    # "Engine Capacity/kW" and apps/ml and apps/depreciation read this exact
    # attribute and API key. Only the labels/messages say "power output";
    # engine displacement is the separate engine_capacity_cc below.
    engine_capacity_kw = models.DecimalField(
        "power output (kW)",
        max_digits=6,
        decimal_places=2,
        help_text="Power output in kW (not engine displacement - see engine_capacity_cc).",
        validators=[
            MinValueValidator(Decimal("0.10"), message="Power output must be between 0.10 kW and 700.00 kW."),
            MaxValueValidator(Decimal("700.00"), message="Power output must be between 0.10 kW and 700.00 kW."),
        ],
    )
    powertrain = models.CharField(max_length=20, choices=Powertrain.choices, blank=True, default="")
    engine_capacity_cc = models.PositiveIntegerField(
        "engine capacity (cc)",
        null=True,
        blank=True,
        help_text="Engine displacement in cc. Required except for battery electric, where it must be empty.",
        validators=[
            MinValueValidator(600, message="Engine capacity must be between 600 cc and 8,000 cc."),
            MaxValueValidator(8000, message="Engine capacity must be between 600 cc and 8,000 cc."),
        ],
    )
    # Run 1 fix batch 3: which JPJ cc road-tax table applies. Always stored:
    # left blank on any write path (form, bulk import, admin, seed, code), it
    # is filled from body_segment by save() - see default_road_tax_class.
    road_tax_class = models.CharField(
        "road-tax class",
        max_length=20,
        choices=RoadTaxClass.choices,
        blank=True,
        help_text=ROAD_TAX_CLASS_HELP_TEXT,
    )
    thumbnail_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)  # soft delete flag (archive)
    # True only while this row is archived BECAUSE its brand was archived
    # (apps.vehicles.archiving) - restoring the brand revives exactly these.
    archived_by_parent = models.BooleanField(default=False, editable=False)

    objects = VehicleModelQuerySet.as_manager()

    class Meta:
        ordering = ["brand__name", "name", "trim"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "name", "trim"],
                name="unique_vehicle_model_per_brand_name_trim",
            ),
            # The one part of the new-vehicle contract existing rows can't
            # violate (no legacy row has powertrain='bev'), so it's safe to
            # enforce in the database. "Required" can't be - legacy rows
            # have no powertrain/cc yet - see powertrain_spec_errors().
            models.CheckConstraint(
                condition=~models.Q(powertrain="bev") | models.Q(engine_capacity_cc__isnull=True),
                name="bev_has_no_engine_capacity_cc",
            ),
        ]

    def __str__(self):
        return f"{self.brand.name} {self.name} {self.trim}".strip()

    def clean(self):
        # Covers the Django admin form (the serializer applies the same
        # rule for the API and bulk import).
        super().clean()
        errors = powertrain_spec_errors(self.powertrain, self.engine_capacity_cc)
        if errors:
            raise ValidationError(errors)
        self._fill_road_tax_class()

    def save(self, *args, **kwargs):
        self._fill_road_tax_class()
        super().save(*args, **kwargs)

    def _fill_road_tax_class(self):
        if not self.road_tax_class:
            self.road_tax_class = default_road_tax_class(self.body_segment)

    @property
    def road_tax_class_is_default(self):
        """False when the stored class differs from the body type's usual one
        (an admin override - worth checking against the VOC)."""
        return self.road_tax_class == default_road_tax_class(self.body_segment)

    @property
    def spec_complete(self):
        """False for rows entered before the new-vehicle contract existed
        (no powertrain/cc yet) - flagged "Needs specs" in the Fleet UI."""
        return not powertrain_spec_errors(self.powertrain, self.engine_capacity_cc)


class VehicleSpecDraftStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    READY = "ready", "Ready"
    NOT_FOUND = "not_found", "Not Found"
    APPROVED = "approved", "Approved"
    # The fetch task hit an unhandled error (network, browser, parsing) -
    # without this, a crashed fetch left the draft stuck in PENDING forever.
    FAILED = "failed", "Failed"


class VehicleSpecDraft(TimeStampedModel):
    """F010 optional stretch goal (the FYP2 build plan
    section 1) - a "Fetch Spec Draft" assist that pre-fills the existing
    single-record Add Vehicle form from one exact variant page of
    paultan.org's structured Car Buyer's Guide (apps.vehicles.
    paultan_research) - the admin picks Brand -> Model -> Variant from
    real listings first - run as a background Celery task
    (apps.vehicles.tasks.fetch_vehicle_spec_draft).

    This is a STAGING table only - nothing here ever creates or touches
    a VehicleModel row directly. The admin's own click on the EXISTING
    Add Vehicle form's save button (VehicleModelViewSet.create, the
    exact same path, serializer validation, and audit logging as fully-
    manual entry) is the only way a vehicle is ever actually created;
    `approved_vehicle` below is set afterward purely for traceability,
    never required for the save itself to succeed.

    Architecturally distinct from the ML dataset's rejected live-
    scraping approach (apps.ml deliberately uses only admin-managed,
    static training data - see apps/ml/data/README_real_data.md): this
    fetches from a stable editorial/manufacturer new-car spec source
    (not peer-to-peer used-car listings), one admin-initiated lookup at
    a time (never a scheduled bulk crawl), and writes only to this
    review-before-persist staging row - never silently to the real
    catalog.

    thumbnail_url is deliberately never part of `proposed_data` - hot-
    linking/displaying another site's car images raises copyright
    questions out of scope here, so that field stays manual-entry-only,
    exactly as it is today.
    """

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="spec_drafts")
    model_name_query = models.CharField(max_length=150)
    trim_query = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20, choices=VehicleSpecDraftStatus.choices, default=VehicleSpecDraftStatus.PENDING
    )
    # The page actually used, so the admin can cross-check the pre-filled
    # values against the real source before saving.
    source_url = models.URLField(blank=True)
    # Whichever of body_segment/model_year/msrp/engine_capacity_kw were
    # successfully extracted - each fetched independently (see
    # apps.vehicles.tasks.fetch_vehicle_spec_draft), never guessed/
    # interpolated. A field that couldn't be extracted is named in
    # `missing_fields` instead of appearing here with a placeholder value.
    proposed_data = models.JSONField(default=dict, blank=True)
    missing_fields = models.JSONField(default=list, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    # Short, admin-facing reason when status=FAILED; blank otherwise.
    error_message = models.CharField(max_length=500, blank=True)
    # Traceability only, per this model's own docstring - never required
    # for the admin's save to succeed, and never set by anything other
    # than the frontend's own fire-and-forget PATCH after a successful
    # VehicleModelViewSet.create() call.
    approved_vehicle = models.ForeignKey(
        VehicleModel, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Spec draft: {self.brand.name} {self.model_name_query} ({self.status})"
