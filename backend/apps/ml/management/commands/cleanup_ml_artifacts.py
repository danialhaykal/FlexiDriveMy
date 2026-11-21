"""QA audit L18: uploaded dataset files (ML_DATASET_UPLOAD_DIR) and
trained model files (ML_MODELS_DIR) accumulate forever - every upload and
every retrain writes a new file, and nothing ever removes an old one once
it's no longer the deployed model or referenced by a run worth keeping.
This is a manually-run maintenance command (not an automatic signal/cron
job), consistent with this project's other admin-triggered maintenance
operations - run it periodically (e.g. from an ops cron) rather than
having every reject/old-deploy path try to clean up after itself.

A file is deleted only if BOTH:
  - it is not the CURRENTLY deployed model (ProductionModel.model_file_path)
  - no MLTrainingRun row still references it as its own dataset_path/
    deployed model, OR the referencing run is older than --keep-days
    (default 30) - a recent run's files are kept regardless of deployed
    status, so a just-rejected run's dataset/metrics stay inspectable for
    a while.
"""

from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.ml.models import MLTrainingRun, ProductionModel


class Command(BaseCommand):
    help = "Delete uploaded ML dataset files and trained model files no longer referenced by anything worth keeping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-days", type=int, default=30,
            help="Never delete a file belonging to a training run newer than this many days (default: 30).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be deleted without actually deleting anything.",
        )

    def handle(self, *args, **options):
        keep_days = options["keep_days"]
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=keep_days)

        production = ProductionModel.objects.filter(pk=1).first()
        deployed_model_path = production.model_file_path if production else ""

        keep_dataset_paths = set(
            MLTrainingRun.objects.filter(created_at__gte=cutoff).values_list("dataset_path", flat=True)
        )
        # Every run (regardless of age) that actually got deployed still
        # has its underlying model file referenced by ProductionModel
        # ONLY if it's the current one - an older deployed run's model
        # file is safe to remove once superseded, same as any other.

        # Batch 6B/follow-up gap: a run that cleared both deployment gates
        # (deploy_eligible=True) saves its winning estimator to disk
        # immediately but doesn't deploy it - that's a SEPARATE, later,
        # human-gated action (UC012 steps 7-8, MLTrainingRunDeployView).
        # Without this, a candidate sitting there waiting for an admin to
        # review and deploy it could be deleted the moment its run
        # crosses the --keep-days cutoff, breaking that pending Deploy
        # action outright (a clean 400, but a self-inflicted one - the
        # candidate itself was never actually stale). Judgment call:
        # protected INDEFINITELY while still pending (deploy_eligible=True,
        # deployed=False), not just for an extra grace period - there's no
        # "this candidate has gone stale" concept anywhere else in the
        # app, and a time-boxed grace period would just reintroduce the
        # same bug on a longer timer. Once deployed (or rejected), a
        # candidate's file follows the normal age-based rule like any
        # other.
        keep_candidate_paths = set(
            MLTrainingRun.objects.filter(Q(created_at__gte=cutoff) | Q(deploy_eligible=True, deployed=False))
            .exclude(candidate_model_file_path="")
            .values_list("candidate_model_file_path", flat=True)
        )

        deleted = []
        for directory in (Path(settings.ML_DATASET_UPLOAD_DIR), Path(settings.ML_MODELS_DIR)):
            if not directory.exists():
                continue
            for file_path in directory.iterdir():
                if not file_path.is_file():
                    continue
                path_str = str(file_path)
                if path_str == deployed_model_path:
                    continue
                if path_str in keep_dataset_paths:
                    continue
                if path_str in keep_candidate_paths:
                    continue
                deleted.append(path_str)
                if not dry_run:
                    file_path.unlink(missing_ok=True)

        verb = "Would delete" if dry_run else "Deleted"
        if deleted:
            self.stdout.write(f"{verb} {len(deleted)} file(s):")
            for path_str in deleted:
                self.stdout.write(f"  {path_str}")
        else:
            self.stdout.write(self.style.SUCCESS("Nothing to clean up."))
