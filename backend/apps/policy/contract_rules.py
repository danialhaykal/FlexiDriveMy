"""The one lookup of a brand's contract terms (audit batch 4/5): the brand's
own active ContractPenaltyRule if it has one, else the single default rule
(brand = null). Shared by the TCO's contract checklist and by the
Subscription's mileage note, so both always quote the same per-km rate."""

from .models import ContractPenaltyRule


def get_contract_rules(brand):
    """(brand_rule, default_rule) - either may be None."""
    brand_rule = ContractPenaltyRule.objects.filter(brand=brand, is_active=True).first()
    default_rule = ContractPenaltyRule.objects.filter(brand__isnull=True, is_active=True).first()
    return brand_rule, default_rule


def excess_mileage_rate(brand):
    """(rate_per_km, "brand" | "default"), or None if no rule applies."""
    brand_rule, default_rule = get_contract_rules(brand)
    if brand_rule is not None:
        return brand_rule.excess_mileage_charge_per_km, "brand"
    if default_rule is not None:
        return default_rule.excess_mileage_charge_per_km, "default"
    return None
