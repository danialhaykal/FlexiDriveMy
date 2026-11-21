"""Run 3 fix batch 6: recalibrate the mileage bands (data). Reversible.

The four band keys are unchanged. Their limits (policy data, 0027) become
    low up to 10,000; standard 10,001-15,000; high 15,001-25,000;
    very high above 25,000, modelled and sold up to 35,000 km a year.
0027 added low/standard/high limits with these defaults; this migration moves
the active policy's very-high limit from 40,000 to 35,000.

ResidualBaseline grid - the method (no new slope is invented):
  Each band is modelled at its representative km a year (apps.policy.mileage:
  the band midpoint, very high's taken up to its 35,000 cap, low fixed at 80%
  of its limit):
      old  low 8,000 / standard 15,000 / high 25,000 / very high 35,000
      new  low 8,000 / standard 12,500 / high 20,000 / very high 30,000
  For each tenure the OLD grid is read as a straight line between its four
  (old representative km, ratio) points, and the NEW ratio of each band is
  that line's value at the band's NEW representative km, rounded half-up to
  4 dp. So the per-km slope is exactly the one the old grid implies; low is
  unchanged (same km); every new value lies between two old ones, so a higher
  band never retains more than a lower band at the same tenure.

  tenure   old low/std/high/vhigh        new low/std/high/vhigh
    12     0.80 0.77 0.74 0.70           0.8000 0.7807 0.7550 0.7200
    24     0.64 0.61 0.57 0.52           0.6400 0.6207 0.5900 0.5450
    36     0.55 0.50 0.45 0.40           0.5500 0.5179 0.4750 0.4250
    48     0.47 0.42 0.38 0.33           0.4700 0.4379 0.4000 0.3550
    60     0.40 0.35 0.31 0.27           0.4000 0.3679 0.3300 0.2900

Every value stays a PLANNING ASSUMPTION (real GFV residuals are set by the lender).

Only rows that still hold the value this migration expects are changed - an
admin's own edit is never overwritten - and the reverse restores exactly the
old values on the rows it changed back. Idempotent both ways.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations

D = Decimal
BANDS = ["low", "standard", "high", "very_high"]
OLD_REPRESENTATIVE_KM = [8000, 15000, 25000, 35000]
NEW_REPRESENTATIVE_KM = [8000, 12500, 20000, 30000]
OLD_GRID = {
    12: ["0.80", "0.77", "0.74", "0.70"],
    24: ["0.64", "0.61", "0.57", "0.52"],
    36: ["0.55", "0.50", "0.45", "0.40"],
    48: ["0.47", "0.42", "0.38", "0.33"],
    60: ["0.40", "0.35", "0.31", "0.27"],
}
OLD_VERY_HIGH_KM_CAP = 40000
NEW_VERY_HIGH_KM_CAP = 35000


def _line(xs, ys, x):
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            return ys[i] + (ys[i + 1] - ys[i]) * D(x - xs[i]) / D(xs[i + 1] - xs[i])
    raise ValueError(x)


def new_grid():
    """{tenure: [new ratio per band]} - the method in the docstring."""
    grid = {}
    for tenure, row in OLD_GRID.items():
        ys = [D(v) for v in row]
        grid[tenure] = [_line(OLD_REPRESENTATIVE_KM, ys, x).quantize(D("0.0001"), ROUND_HALF_UP)
                        for x in NEW_REPRESENTATIVE_KM]
    return grid


def _apply(apps, from_grid, to_grid, from_cap, to_cap):
    ResidualBaseline = apps.get_model("policy", "ResidualBaseline")
    SubscriptionPolicy = apps.get_model("policy", "SubscriptionPolicy")
    for tenure in OLD_GRID:
        for band, before, after in zip(BANDS, from_grid[tenure], to_grid[tenure]):
            ResidualBaseline.objects.filter(
                is_active=True, tenure_months=tenure, mileage_band=band, ratio=D(before)
            ).update(ratio=D(after))
    SubscriptionPolicy.objects.filter(is_active=True, very_high_km_cap=from_cap).update(very_high_km_cap=to_cap)


def forwards(apps, schema_editor):
    old = {t: [D(v) for v in row] for t, row in OLD_GRID.items()}
    _apply(apps, old, new_grid(), OLD_VERY_HIGH_KM_CAP, NEW_VERY_HIGH_KM_CAP)


def backwards(apps, schema_editor):
    old = {t: [D(v) for v in row] for t, row in OLD_GRID.items()}
    _apply(apps, new_grid(), old, NEW_VERY_HIGH_KM_CAP, OLD_VERY_HIGH_KM_CAP)


class Migration(migrations.Migration):
    dependencies = [("policy", "0027_mileage_band_definition")]

    operations = [migrations.RunPython(forwards, backwards)]
