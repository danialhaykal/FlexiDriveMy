from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.constants import MAX_GFV_RESIDUAL_RATIO, MAX_TENURE_MONTHS, MIN_TENURE_MONTHS
from apps.common.models import TimeStampedModel
from apps.vehicles.models import Brand, Powertrain, RoadTaxClass, VehicleModel

from .rule_text import model_name_candidates, model_name_in_text_message, validate_no_ringgit_fee_amounts


class InterestRate(TimeStampedModel):
    """F011 - a dealer's annual FLAT interest rate (the 'r' in HP_monthly:
    interest charged on the original balance for the whole term, the way a
    dealer quotes a campaign rate), constrained to 0.01%-15.00% per
    the project spec's boundary rule. It is NOT a reducing-balance/effective rate:
    the app derives that separately (apps.comparisons.formulas.
    effective_annual_rate) and shows it beside this one. The field and API
    key keep the name rate_percent."""

    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="interest_rates")
    rate_percent = models.DecimalField(
        "flat rate (% p.a.)",
        help_text=(
            "The dealer's flat campaign rate, % p.a. on the original balance. The app derives "
            "the effective (reducing-balance) rate from it - do not enter an effective rate here."
        ),
        max_digits=6,
        decimal_places=4,
        validators=[
            # QA audit L1: exact UC011 alternate-flow copy, not a DRF-
            # generic/paraphrased message. "%%" (not a literal "%") is
            # deliberate - see apps.policy.serializers.
            # INTEREST_RATE_RANGE_MESSAGE's own comment for why a literal
            # "%" crashes here (Django formats this message as
            # `message % params` when raising).
            MinValueValidator(
                Decimal("0.01"),
                message="Interest rate input exceeds acceptable limits (0.01%% – 15.00%%).",
            ),
            MaxValueValidator(
                Decimal("15.00"),
                message="Interest rate input exceeds acceptable limits (0.01%% – 15.00%%).",
            ),
        ],
    )
    is_active = models.BooleanField(default=True)  # soft delete flag
    # True only while archived BECAUSE its brand was (apps.vehicles.archiving).
    archived_by_parent = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["brand__name"]
        constraints = [
            # QA audit H12: a brand could end up with several active
            # rates at once, and apps.comparisons.services.get_active_interest_rate's
            # .filter(...).first() would then pick an arbitrary one (in
            # practice the oldest) - an admin's rate change was silently
            # ignored by the live calculation engine, breaking UC011's
            # "immediate effect" rule. DB-enforced so it can never happen
            # again regardless of code path (API, admin, management
            # command).
            models.UniqueConstraint(
                fields=["brand"],
                condition=models.Q(is_active=True),
                name="unique_active_interest_rate_per_brand",
            )
        ]

    def __str__(self):
        return f"{self.brand.name} @ {self.rate_percent}%"


class MileageBand(models.TextChoices):
    """QA audit M11 replaced an earlier, undocumented split whose labels let one
    km figure fall in two bands; Run 3 fix batch 6 recalibrated the ranges and
    made every boundary "up to and including" the band's limit, so no km figure
    falls in two bands.

    The four band IDENTIFIERS (low/standard/high/very_high) are
    deliberately UNCHANGED - only what real-world km range each one
    represents moves. This is a judgment call, not an oversight: there is
    no data-driven way to split an existing admin-configured
    ResidualValueMatrix row's residual_value_ratio (a brand's chosen
    rate for an entire band, not a figure derived from actual observed
    mileage) across a redrawn boundary - e.g. the old STANDARD band's
    rate can't be algorithmically divided into "the part that was really
    10k-15k" vs "the part that was really 15k-20k, now HIGH" when no such
    split ever existed in the source data. Keeping the same four keys
    means every existing row carries over under its own identifier with
    no row-level remapping needed - the alternative (inventing a new
    band scheme and guessing which old rows map to which new ones) would
    replace a real discrepancy with a fabricated one. The real content
    implication - an admin's existing STANDARD-band rate now also covers
    what used to be classed HIGH - is a deliberate, flagged follow-up for
    admins to review their own rates against, not something the system can
    correct on their behalf.

    Run 3 fix batch 6: the km RANGES are no longer written here at all. They
    are policy data - SubscriptionPolicy's four included-km fields - and
    apps.policy.mileage is the one place that turns them into ranges, labels,
    representative km and the km-to-band mapping. These choices carry only the
    band names, so no km figure can go stale in a label.
    """

    LOW = "low", "Low"
    STANDARD = "standard", "Standard"
    HIGH = "high", "High"
    VERY_HIGH = "very_high", "Very high"


class ResidualValueMatrix(TimeStampedModel):
    """F011 - an OPTIONAL per-brand override of the GFV residual ratio
    (G_ratio in the project spec's GFV formulas), keyed by brand + tenure + mileage
    band. Since audit batch 4 nothing needs to be keyed here: when there is
    no active row, apps.policy.residuals estimates the ratio from
    ResidualBaseline + ResidualAdjustment; a row here wins over that
    estimate. Stored as a fraction (0-1), e.g. 0.5000 for the 50% used in
    the GFV reference test case."""

    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="residual_value_ratios")
    tenure_months = models.PositiveIntegerField(
        validators=[
            MinValueValidator(MIN_TENURE_MONTHS, message="Tenure must be between 12 and 108 months."),
            MaxValueValidator(MAX_TENURE_MONTHS, message="Tenure must be between 12 and 108 months."),
        ]
    )
    mileage_band = models.CharField(max_length=20, choices=MileageBand.choices)
    residual_value_ratio = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        validators=[
            MinValueValidator(
                Decimal("0.0001"),
                message=f"Residual value ratio must be between 0.01% and {MAX_GFV_RESIDUAL_RATIO:.0%}.",
            ),
            # QA audit M15: capped at 1 - MIN_DOWNPAYMENT_RATIO, not
            # 100% - see MAX_GFV_RESIDUAL_RATIO's own comment for why a
            # higher ratio can never produce a valid GFV offering once
            # C6's 10% minimum downpayment always applies.
            MaxValueValidator(
                MAX_GFV_RESIDUAL_RATIO,
                message=f"Residual value ratio must be between 0.01% and {MAX_GFV_RESIDUAL_RATIO:.0%}.",
            ),
        ],
    )
    is_active = models.BooleanField(default=True)  # soft delete flag
    # True only while archived BECAUSE its brand was (apps.vehicles.archiving).
    archived_by_parent = models.BooleanField(default=False, editable=False)

    class Meta:
        verbose_name_plural = "residual value matrices"
        ordering = ["brand__name", "tenure_months", "mileage_band"]
        constraints = [
            # QA audit M18: scoped to active rows only - the constraint
            # previously applied regardless of is_active, so an archived
            # cell permanently occupied its (brand, tenure, mileage_band)
            # key and a genuine replacement could never be created again.
            models.UniqueConstraint(
                fields=["brand", "tenure_months", "mileage_band"],
                condition=models.Q(is_active=True),
                name="unique_active_residual_ratio_per_brand_tenure_band",
            )
        ]

    def __str__(self):
        return f"{self.brand.name} t={self.tenure_months}mo {self.mileage_band} -> {self.residual_value_ratio}"


# --- Residual-value estimator tables (audit batch 4) ---------------------
# The estimator (apps.policy.residuals) gives every vehicle a GFV residual
# with nothing keyed per car or per brand: baseline(tenure, band) + brand
# adjustment + powertrain adjustment. ResidualValueMatrix above is now an
# optional per-brand OVERRIDE that wins over the estimate. Every seeded
# figure is a planning assumption (see each row's source_note), not market
# data or a lender's real GFV.


class ResidualBaseline(TimeStampedModel):
    """Share of the price retained after `tenure_months` at `mileage_band`,
    before any brand or powertrain adjustment. Falls as tenure and mileage
    rise. Tenures with no baseline row are not offered as GFV."""

    tenure_months = models.PositiveIntegerField(
        validators=[
            MinValueValidator(MIN_TENURE_MONTHS, message="Tenure must be between 12 and 108 months."),
            MaxValueValidator(MAX_TENURE_MONTHS, message="Tenure must be between 12 and 108 months."),
        ]
    )
    mileage_band = models.CharField(max_length=20, choices=MileageBand.choices)
    ratio = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001")), MaxValueValidator(Decimal("1"))],
    )
    source_note = models.TextField(blank=True)
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)  # soft delete flag

    class Meta:
        ordering = ["tenure_months", "mileage_band"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenure_months", "mileage_band"],
                condition=models.Q(is_active=True),
                name="unique_active_residual_baseline_per_tenure_band",
            )
        ]

    def __str__(self):
        return f"Baseline {self.tenure_months}mo {self.mileage_band} -> {self.ratio}"


class ResidualAdjustment(TimeStampedModel):
    """A signed shift, in ratio points (0.06 = +6 points), added to the
    baseline for one brand OR one powertrain - exactly one of the two. A
    brand or powertrain with no active row simply gets 0, so a new brand is
    never an error."""

    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.PROTECT, related_name="residual_adjustments"
    )
    powertrain = models.CharField(max_length=20, choices=Powertrain.choices, blank=True)
    delta_points = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("-0.5")), MaxValueValidator(Decimal("0.5"))],
    )
    source_note = models.TextField(blank=True)
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)  # soft delete flag

    class Meta:
        ordering = ["powertrain", "brand__name"]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(brand__isnull=False, powertrain="") | models.Q(brand__isnull=True) & ~models.Q(powertrain="")),
                name="residual_adjustment_exactly_one_of_brand_or_powertrain",
            ),
            models.UniqueConstraint(
                fields=["brand"],
                condition=models.Q(is_active=True, brand__isnull=False),
                name="unique_active_residual_adjustment_per_brand",
            ),
            models.UniqueConstraint(
                fields=["powertrain"],
                condition=models.Q(is_active=True) & ~models.Q(powertrain=""),
                name="unique_active_residual_adjustment_per_powertrain",
            ),
        ]

    def __str__(self):
        target = self.brand.name if self.brand_id else self.get_powertrain_display()
        return f"Residual adjustment {target}: {self.delta_points:+}"


class MCDACriterion(models.TextChoices):
    UPFRONT_CASH_PRESERVATION = "upfront_cash_preservation", "Upfront Cash Preservation"
    MAINTENANCE_PROTECTION = "maintenance_protection", "Maintenance Protection"
    OWNERSHIP_EQUITY = "ownership_equity", "Ownership Equity"


class MCDACriteriaWeight(TimeStampedModel):
    """F011 - admin-configured default weight per MCDA criterion (the project spec:
    Score_i = Sum(w_j * s_ij)). Exactly one row per MCDACriterion value;
    active rows' weights must always sum to 1.0 (enforced in the serializer,
    since it's a cross-row invariant a single-column CHECK can't express).
    These are policy defaults an end user's own comparison can override
    later — that per-comparison override flow isn't built yet.

    STATUS (audit batch 6, F4): REFERENCE ONLY. Nothing in scoring (or the
    TCO, Arena, exports or saved scenarios) reads this table: the
    recommendation uses only the buyer's own three priority ratings
    (apps.scoring.formulas.normalize_priority_weights). It is only edited and
    listed through apps.policy.views.MCDAWeightsView, labelled "Default
    Priority Weights" in Policy Configuration with that caveat. Not wired into
    scoring on purpose (that would change the recommendation flow); not
    deleted either, so a future default-priorities feature has its data.
    """

    criterion = models.CharField(max_length=40, choices=MCDACriterion.choices, unique=True)
    default_weight = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["criterion"]

    def __str__(self):
        return f"{self.get_criterion_display()}: {self.default_weight}"


class SubscriptionPlan(TimeStampedModel):
    """F011 - a vehicle's subscription-path commercial terms: the inputs to
    F005's Subscription NetCost formula (the project spec). Admin-managed, like
    InterestRate/ResidualValueMatrix; one ACTIVE plan per vehicle.

    QA audit Batch 6A: was a OneToOneField, which enforces uniqueness on
    `vehicle` UNCONDITIONALLY at the DB level - archiving the old plan
    (is_active=False) would NOT have freed up the slot for a replacement,
    since a OneToOneField can't be scoped to "only among active rows" the
    way InterestRate/ResidualValueMatrix's own constraints already are.
    Changed to a plain ForeignKey + the same conditional UniqueConstraint
    pattern (see Meta below), so "archive the old one, then create the
    replacement" - the exact workflow SubscriptionPlanSerializer.validate()
    below asks for - actually works. `related_name` is now plural
    (`subscription_plans`, a manager) since a vehicle can legitimately
    have more than one row over time (just never more than one ACTIVE
    one) - the one production call site that reads this
    (apps.comparisons.services.get_active_subscription_plan) already
    queried by `.filter(vehicle=vehicle, is_active=True).first()` rather
    than using the old singular reverse accessor, so this is not a
    behavior change for anything except direct ORM access to the reverse
    relation (one test fixture updated accordingly).

    Audit batch 5: a plan is now an optional PROVIDER-QUOTE OVERRIDE. With no
    active plan the fee is estimated by apps.policy.subscription_pricing from
    depreciation, funding, running costs and a margin (SubscriptionPolicy), so
    a new car needs nothing keyed. A plan's fee_monthly is used exactly, and
    does not change with tenure or mileage band - that is what a quote means.
    """

    vehicle = models.ForeignKey(
        VehicleModel, on_delete=models.CASCADE, related_name="subscription_plans"
    )
    fee_monthly = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"), message="Monthly fee must be a positive amount.")],
    )
    # Deprecated: derived by apps.policy.operating_costs. Nothing reads these
    # three any more - the columns stay (existing rows, saved scenarios and
    # audit history) but are optional and default to 0.00.
    insurance_annual = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Deprecated: derived by apps.policy.operating_costs.",
    )
    road_tax_annual = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Deprecated: derived by apps.policy.operating_costs.",
    )
    maintenance_annual = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Deprecated: derived by apps.policy.operating_costs.",
    )
    is_active = models.BooleanField(default=True)  # soft delete flag
    # True only while archived BECAUSE its vehicle (or that vehicle's brand)
    # was archived (apps.vehicles.archiving).
    archived_by_parent = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["vehicle"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle"],
                condition=models.Q(is_active=True),
                name="unique_active_subscription_plan_per_vehicle",
            )
        ]

    def __str__(self):
        return f"Subscription plan for {self.vehicle}"


class SubscriptionPolicy(TimeStampedModel):
    """The single set of assumptions apps.policy.subscription_pricing prices a
    Subscription with (audit batch 5). Data, not code: every value is a
    PLANNING ASSUMPTION, not provider data - real subscription terms vary by
    provider - and the seeded row's source_note says so. Edited in Django
    admin. At most one ACTIVE row.
    """

    min_tenure_months = models.PositiveIntegerField(
        default=12, validators=[MinValueValidator(1)], help_text="Shortest subscription offered."
    )
    max_tenure_months = models.PositiveIntegerField(
        default=36, validators=[MinValueValidator(1)], help_text="Longest subscription offered."
    )
    funding_rate_percent = models.DecimalField(
        max_digits=6, decimal_places=4, default=Decimal("4.5000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="The provider's cost of capital, nominal % p.a.",
    )
    margin_percent = models.DecimalField(
        max_digits=6, decimal_places=4, default=Decimal("12.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1000"))],
        help_text="Provider margin on its cost, %.",
    )
    deposit_months = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("2.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Refundable security deposit, in months of fee.",
    )
    # Run 3 fix batch 6: the mileage bands' ONE definition. Each value is the
    # band's upper limit in km a year (inclusive) and the km a Subscription in
    # that band includes; apps.policy.mileage derives every range, label,
    # representative km and the km-to-band mapping from these four fields.
    # Planning assumptions, editable here - the defaults below are the seeded values.
    low_km_cap = models.PositiveIntegerField(
        "low band: up to (km a year)", default=10000, validators=[MinValueValidator(1)],
        help_text="Upper limit of the low mileage band, and the km a year a low-band subscription includes.",
    )
    standard_km_cap = models.PositiveIntegerField(
        "standard band: up to (km a year)", default=15000, validators=[MinValueValidator(1)],
        help_text="Upper limit of the standard mileage band, and the km a year it includes.",
    )
    high_km_cap = models.PositiveIntegerField(
        "high band: up to (km a year)", default=25000, validators=[MinValueValidator(1)],
        help_text="Upper limit of the high mileage band, and the km a year it includes.",
    )
    very_high_km_cap = models.PositiveIntegerField(
        "very high band: modelled and sold up to (km a year)", default=35000, validators=[MinValueValidator(1)],
        help_text="The very high band is open-ended; this is the km a year it is modelled and sold up to.",
    )
    source_note = models.TextField(blank=True)
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)  # soft delete flag

    class Meta:
        verbose_name_plural = "subscription policies"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_tenure_months__lte=models.F("max_tenure_months")),
                name="subscription_policy_min_lte_max_tenure",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(low_km_cap__lt=models.F("standard_km_cap"))
                    & models.Q(standard_km_cap__lt=models.F("high_km_cap"))
                    & models.Q(high_km_cap__lt=models.F("very_high_km_cap"))
                ),
                name="subscription_policy_band_km_ascending",
            ),
            # One ACTIVE policy: among active rows is_active can only appear once.
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="unique_active_subscription_policy",
            ),
        ]

    def __str__(self):
        return f"Subscription policy: {self.min_tenure_months}-{self.max_tenure_months} months"

    def clean(self):
        super().clean()
        caps = [self.low_km_cap, self.standard_km_cap, self.high_km_cap, self.very_high_km_cap]
        if all(c is not None for c in caps) and not all(a < b for a, b in zip(caps, caps[1:])):
            raise ValidationError(BAND_KM_ASCENDING_MESSAGE)


BAND_KM_ASCENDING_MESSAGE = "Each mileage band's km a year must be higher than the band below it."


class OperatingCostBand(TimeStampedModel):
    """DEPRECATED (audit batch 2): nothing reads this table any more. Road
    tax, insurance and maintenance are now derived per vehicle by
    apps.policy.operating_costs from RoadTaxCcBand / EvRoadTaxGroup /
    OperatingCostRate. The table and its rows are kept (no destructive
    migration) and stay visible in Django admin, but it is no longer in the
    API or the Policy Configuration page.

    Original purpose - F006's TCO calculation (UC006 Rule 1) needed Malaysian road tax and
    comprehensive insurance estimates banded by engine capacity, plus a
    maintenance estimate - sourced from UC006's referenced 'operating cost
    parameter tables (UC011)'. UC011 as its own full admin feature isn't
    built yet, so this is a minimal admin-manageable model filling that
    data gap, distinct from SubscriptionPlan above: that's a per-vehicle
    subscription's *inclusive* fee offset, this is the market-rate cost an
    HP/GFV owner pays out of pocket, standardized by engine size.
    """

    min_engine_capacity_kw = models.DecimalField(max_digits=6, decimal_places=2)
    max_engine_capacity_kw = models.DecimalField(max_digits=6, decimal_places=2)
    road_tax_annual = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    insurance_annual = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    maintenance_annual = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    is_active = models.BooleanField(default=True)  # soft delete flag

    class Meta:
        ordering = ["min_engine_capacity_kw"]
        # Run 1 fix batch 5 (D4): read-only in Django admin under this title.
        verbose_name = "operating cost band (deprecated - not used)"
        verbose_name_plural = "Operating cost bands (deprecated - not used)"

    def __str__(self):
        return f"{self.min_engine_capacity_kw}-{self.max_engine_capacity_kw} kW"


# --- Operating-cost rate tables (audit batch 2) ---------------------------
# Data, not code: a government rate change is a data edit in Django admin.
# apps.policy.operating_costs reads them; nothing is keyed in per vehicle.
# Every table carries where its figures came from and when they took effect,
# so the Policy Configuration page can show the provenance.


class FuelSchedule(models.TextChoices):
    """NO LONGER READ (run 1 fix batch 3). Audit batch 3 seeded a separate
    diesel cc schedule from a single 2006 article; current sources (StashAway
    2026, paultan, Carso) describe none - diesel uses the same cc tables as
    petrol, and the registration class (saloon / non-saloon) decides which.
    The diesel rows are archived and the field is kept only so no migration
    rewrites history."""

    PETROL = "petrol", "Petrol"
    DIESEL = "diesel", "Diesel"


class RoadTaxCcBand(TimeStampedModel):
    """JPJ private-car road tax by engine displacement (Peninsular Malaysia).
    Used for every powertrain except battery electric - petrol, diesel and
    hybrids alike - from the table for the car's registration class
    (vehicle_class: saloon or non-saloon, VehicleModel.road_tax_class).

    Annual road tax = base_amount + (cc - threshold_cc) * per_cc_rate for
    the band containing the exact cc. Flat bands have threshold_cc = 0 and
    per_cc_rate = 0.
    """

    # Not read any more - see FuelSchedule.
    fuel_schedule = models.CharField(max_length=10, choices=FuelSchedule.choices, default=FuelSchedule.PETROL)
    vehicle_class = models.CharField(max_length=20, choices=RoadTaxClass.choices, default=RoadTaxClass.SALOON)
    min_cc = models.PositiveIntegerField()
    max_cc = models.PositiveIntegerField()
    base_amount = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    threshold_cc = models.PositiveIntegerField(default=0)
    per_cc_rate = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))]
    )
    source_note = models.TextField(blank=True)
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)  # soft delete flag

    class Meta:
        ordering = ["vehicle_class", "min_cc"]
        constraints = [
            models.CheckConstraint(condition=models.Q(min_cc__lte=models.F("max_cc")), name="road_tax_cc_band_min_lte_max"),
            # One ACTIVE band per (class, starting cc): the saloon and
            # non-saloon tables each have their own 0-1,000 cc band.
            models.UniqueConstraint(
                fields=["vehicle_class", "min_cc"],
                condition=models.Q(is_active=True),
                name="unique_active_road_tax_cc_band_per_class_min",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_vehicle_class_display()} {self.min_cc}-{self.max_cc} cc: "
            f"RM{self.base_amount} + RM{self.per_cc_rate}/cc over {self.threshold_cc}"
        )


class EvRoadTaxGroup(TimeStampedModel):
    """JPJ battery-electric road tax by motor power, effective 1 Jan 2026.
    Used only for powertrain = bev.

    The group is the first (lowest) one whose max_kw covers the vehicle's
    kW (max_kw null = open-ended top group). Annual tax = base_amount while
    kW <= base_until_kw, then + increment_per_10kw for each further 10 kW
    block, rounded UP: blocks = ceil((kW - base_until_kw) / 10). A group
    with no base_until_kw is a fixed amount.
    """

    label = models.CharField(max_length=2)
    min_kw = models.DecimalField(max_digits=8, decimal_places=3)
    max_kw = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    base_amount = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    base_until_kw = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    increment_per_10kw = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))]
    )
    source_note = models.TextField(blank=True)
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)  # soft delete flag

    class Meta:
        ordering = ["min_kw"]
        constraints = [
            models.UniqueConstraint(
                fields=["label"], condition=models.Q(is_active=True), name="unique_active_ev_road_tax_group_label"
            ),
        ]

    def __str__(self):
        return f"Group {self.label}: {self.min_kw}-{self.max_kw or 'up'} kW"


class OperatingCostRate(TimeStampedModel):
    """Insurance and maintenance as percentage ESTIMATES, one active row per
    powertrain. These are labelled planning assumptions (see source_note),
    not published tariffs - edit them in Django admin.

    insurance_rate_percent: annual comprehensive premium as a percent of
    the vehicle's price (sum insured taken as MSRP) BEFORE the buyer's
    No-Claim Discount, which apps.policy.operating_costs applies for owner
    running costs. maintenance_rate_percent: annual servicing and wear items
    as a percent of price, never below maintenance_floor_annual and never
    above maintenance_cap_annual (when set).
    """

    powertrain = models.CharField(max_length=20, choices=Powertrain.choices)
    insurance_rate_percent = models.DecimalField(
        max_digits=6, decimal_places=4, validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]
    )
    maintenance_rate_percent = models.DecimalField(
        max_digits=6, decimal_places=4, validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]
    )
    maintenance_floor_annual = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    # Run 1 fix batch 3 (C4): a planning-assumption ceiling, like the
    # percentage - 1% of a RM 1.43m 911 is not what servicing costs. Empty = no cap.
    maintenance_cap_annual = models.DecimalField(
        "maintenance cap (RM a year)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Planning assumption, not a tariff. Maintenance is never costed above this; leave empty for no cap.",
    )
    source_note = models.TextField(blank=True)
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)  # soft delete flag

    class Meta:
        ordering = ["powertrain"]
        constraints = [
            models.UniqueConstraint(
                fields=["powertrain"], condition=models.Q(is_active=True), name="unique_active_operating_cost_rate_per_powertrain"
            ),
        ]

    def __str__(self):
        return f"{self.get_powertrain_display()}: insurance {self.insurance_rate_percent}%, maintenance {self.maintenance_rate_percent}%"


class ContractPenaltyRule(TimeStampedModel):
    """Batch 6A / UC011 - "contract penalty rules", one of the parameter
    sets UC011's main flow explicitly lists admins configuring, and one
    of the values UC006's contract-return checklist (a later batch) will
    need to read instead of hardcoded placeholder text ("wear-and-tear
    tolerances, excess mileage charges, and early termination fees" -
    UC006 main flow step 8's exact wording).

    Judgment call, flagged explicitly: neither the project spec nor the use-case
    tables specify this model's exact schema. Keyed by BRAND (not per
    vehicle) - a contract term policy decision, same granularity
    InterestRate already uses, not a per-vehicle figure. Deliberately
    minimal:
      - excess_mileage_charge_per_km: a flat per-km rate, not a formula -
        the project spec doesn't define a mileage-overage formula.
      - early_termination_fee: a flat fee, not a formula - the project spec
        doesn't define an early-termination calculation either (that
        would need real Rule-of-78/unearned-interest logic, well beyond
        what this batch's own M19 disclosure already flags as missing).
      - wear_tear_tolerance_description: free text, since there is no
        quantifiable tolerance formula in the FYP1 report to encode as
        actual fields.
    This shape is a judgment call a LATER batch (UC006's checklist) will
    consume as a reader, not the other way around - deliberately kept
    this simple rather than over-engineered for a consumer that doesn't
    exist yet.

    Audit batch 4: a row with NO brand is the single DEFAULT rule every
    brand without its own row uses (so a new brand needs no keying), and the
    early-termination term is N months of the instalment shown on the
    report (early_termination_months), never a stored ringgit amount. A
    brand row may leave the months empty to inherit the default's. Wear and
    tear is a checklist text only - normal wear is already priced into the
    residual, so it is not modelled as a cost.
    """

    # Audit batch 4: brand is nullable - the row with NO brand is the single
    # default rule every brand without its own row falls back to, so a new
    # brand gets sensible contract terms with nothing keyed.
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.PROTECT, related_name="contract_penalty_rules"
    )
    excess_mileage_charge_per_km = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"), message="Excess mileage charge must be a positive amount.")],
    )
    # DEPRECATED (audit batch 4) and not read: a stored ringgit amount copied
    # from one car cannot be right for another. The column stays so nothing
    # is destroyed; early_termination_months replaces it.
    early_termination_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"), message="Early termination fee must be a positive amount.")],
        help_text="Deprecated and not read: use early_termination_months.",
    )
    # Run 1 (B7): months of the SUBSCRIPTION fee charged for returning a
    # subscription car early (KINTO ONE's published rule: N months' fee, or
    # the fees left, whichever is lower). The fee is N x the Subscription fee
    # of the request on screen, computed at response time - never stored.
    # Settling a Hire Purchase loan early is a different thing with no
    # penalty (reducing balance - see settlement_balance). Empty on a brand
    # rule means "use the default rule's months". Field name kept.
    early_termination_months = models.DecimalField(
        "subscription early-return fee (months of fee)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"), message="Early termination months must be a positive number.")],
        help_text=(
            "Months of the subscription fee charged for returning a subscription car early (or the fees left, "
            "whichever is lower). Empty = use the default rule. Settling a Hire Purchase loan early has no penalty."
        ),
    )
    # Checklist text only. Fee amounts must not be typed here: they go stale
    # and contradict the screen (the app computes every fee).
    wear_tear_tolerance_description = models.TextField(validators=[validate_no_ringgit_fee_amounts])
    source_note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)  # soft delete flag
    # True only while archived BECAUSE its brand was (apps.vehicles.archiving).
    archived_by_parent = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["brand__name"]
        constraints = [
            # Same "one ACTIVE row per key" pattern as InterestRate -
            # archive the old rule first, then create the replacement,
            # rather than ever having two active rules for one brand.
            models.UniqueConstraint(
                fields=["brand"],
                condition=models.Q(is_active=True),
                name="unique_active_contract_penalty_rule_per_brand",
            ),
            # NULLs never collide in a plain unique index, so the default
            # rule (no brand) needs its own guard: among active rows with no
            # brand, is_active can only appear once.
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True, brand__isnull=True),
                name="unique_active_default_contract_penalty_rule",
            ),
        ]

    def __str__(self):
        if self.brand_id is None:
            return "Default contract penalty rule"
        return f"Contract penalty rule for {self.brand.name}"

    def clean(self):
        # Django admin (the model form calls this); the API serializer runs the same check.
        super().clean()
        errors = contract_rule_errors(
            brand_id=self.brand_id,
            early_termination_months=self.early_termination_months,
            wear_tear_tolerance_description=self.wear_tear_tolerance_description,
        )
        if errors:
            raise ValidationError(errors)


def early_return_months_message(max_tenure_months):
    return (
        f"The early-return fee can't be more than {max_tenure_months} months of fee - the longest subscription plan "
        f"is {max_tenure_months} months."
    )


def contract_rule_errors(*, brand_id, early_termination_months, wear_tear_tolerance_description):
    """Run 3 fix batch 4 - {field: message} for a contract rule's values, empty when fine.

    F-15: the subscription early-return fee is N months of fee, so N may not exceed
    the longest subscription the active SubscriptionPolicy offers (read from that
    row, never a fixed 36; no active policy = no Subscription, nothing to cap). The
    field's own validator already refuses 0 and below.
    F-16: a brand's rule applies to every car of the brand, so its wear-and-tear
    text may not name one of that brand's models (any case) - the same check the
    live-text regression test and refresh_contract_rule_texts use. The default rule
    (no brand) has no models of its own.
    """
    errors = {}
    if early_termination_months is not None:
        policy = SubscriptionPolicy.objects.filter(is_active=True).first()
        if policy is not None and early_termination_months > policy.max_tenure_months:
            errors["early_termination_months"] = early_return_months_message(policy.max_tenure_months)
    if brand_id is not None and wear_tear_tolerance_description:
        names = model_name_candidates(VehicleModel.objects.filter(brand_id=brand_id).values_list("name", "trim"))
        message = model_name_in_text_message(wear_tear_tolerance_description, names)
        if message:
            errors["wear_tear_tolerance_description"] = message
    return errors
