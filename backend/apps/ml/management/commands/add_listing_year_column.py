"""One-off (ML batch 2): add the Listing_Year column to
apps/ml/data/raw/resale_car.csv in place - 2022 for the Kaggle rows, 2026 for
the 30 hand-collected rows. See apps/ml/listing_year.py for the asserts. A
second run refuses (the column is already there) and writes nothing."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.ml.listing_year import ListingYearError, add_listing_year_column

RAW_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "resale_car.csv"


class Command(BaseCommand):
    help = "Add Listing_Year to apps/ml/data/raw/resale_car.csv in place (2022 Kaggle rows, 2026 hand-collected rows)."

    def handle(self, *args, **options):
        raw = RAW_PATH.read_bytes()
        try:
            new, report = add_listing_year_column(raw)
        except ListingYearError as exc:
            raise CommandError(str(exc)) from exc
        for line in report:
            self.stdout.write(line)
        RAW_PATH.write_bytes(new)
        self.stdout.write(self.style.SUCCESS(f"Wrote {RAW_PATH} ({len(raw):,} -> {len(new):,} bytes)"))
