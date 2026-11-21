"""Generates apps/ml/data/synthetic_historical_pricing.csv - SYNTHETIC
placeholder data (see apps/ml/data/README.md), not real transactions.

Deterministic (fixed random seed) so the checked-in CSV can be regenerated
byte-for-byte if this script changes.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand

OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "synthetic_historical_pricing.csv"

# brand_code -> assumed new-car MSRP, used only to generate a plausible
# depreciation curve per synthetic "brand".
BRAND_BASE_MSRP = {1: 180000, 2: 120000, 3: 90000, 4: 70000, 5: 50000}
ROWS_PER_BRAND = 500
RANDOM_SEED = 42


class Command(BaseCommand):
    help = "Regenerate the synthetic historical used-car pricing dataset for F012."

    def handle(self, *args, **options):
        rng = np.random.default_rng(RANDOM_SEED)
        rows = []

        for brand_code, base_msrp in BRAND_BASE_MSRP.items():
            for _ in range(ROWS_PER_BRAND):
                vehicle_age = rng.uniform(0, 10)
                # Mileage is cumulative odometer reading (correlated with
                # age), not an annual rate - realistic for a used-car
                # listing dataset.
                annual_mileage_rate = rng.uniform(8000, 18000)
                mileage = max(0, vehicle_age * annual_mileage_rate + rng.normal(0, 2000))

                depreciation_factor = 0.85**vehicle_age  # ~15%/year compounding
                mileage_penalty = max(0.70, 1 - mileage * 0.000003)
                noise = rng.normal(1.0, 0.03)  # +/-3% price noise

                resale_price = max(1000, base_msrp * depreciation_factor * mileage_penalty * noise)

                rows.append(
                    {
                        "vehicle_age": round(vehicle_age, 2),
                        "mileage": round(mileage, 0),
                        "resale_price": round(resale_price, 2),
                        "brand_code": brand_code,
                    }
                )

        df = pd.DataFrame(rows).sample(frac=1, random_state=RANDOM_SEED).reset_index(drop=True)
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUTPUT_PATH, index=False)

        self.stdout.write(self.style.SUCCESS(f"Wrote {len(df)} synthetic rows to {OUTPUT_PATH}"))
