import uuid
from pathlib import Path

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import get_client_ip
from apps.users.permissions import IsAdminRole

from . import training as training_module
from .models import MLTrainingRun, ProductionModel, TrainingRunStatus
from .serializers import MLTrainingRunSerializer, ProductionModelSerializer
from .tasks import deploy_training_run, run_training_task

RETIRED_RUN_MESSAGE = "This run has been retired."


class MLDatasetUploadView(APIView):
    """F012 - UC012 main flow steps 2-4 (upload + validate + trigger
    retrain) and alternate flow (malformed CSV, UC012 3.1-3.4).

    Column validation happens here, synchronously, so a malformed upload
    is rejected immediately (400) with nothing touched - no training run
    row created, no file saved, no dispatch to Celery. A well-formed
    upload is saved to disk (so the out-of-process Celery task can read it
    independently) and handed off as a background training run.
    """

    permission_classes = [IsAdminRole]
    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "No file uploaded."}, status=status.HTTP_400_BAD_REQUEST)

        # QA audit L18: a sane upload size ceiling - see
        # settings.ML_DATASET_MAX_UPLOAD_SIZE_BYTES's own comment.
        if uploaded_file.size > settings.ML_DATASET_MAX_UPLOAD_SIZE_BYTES:
            max_mb = settings.ML_DATASET_MAX_UPLOAD_SIZE_BYTES / (1024 * 1024)
            return Response(
                {"detail": f"Dataset upload failed. File exceeds the {max_mb:.0f}MB size limit."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # QA audit L18: reject a new upload while one is already RUNNING,
        # rather than letting two retrains race for the same
        # ProductionModel/model-file-on-disk slot. Both writing results
        # to DIFFERENT files and both calling _deploy() concurrently is a
        # genuine, if narrow, race (whichever finishes last "wins"
        # regardless of which actually has the better model) - simplest
        # safe fix is just not letting it start, not a locking scheme for
        # a feature with normally one admin operating it.
        if MLTrainingRun.objects.filter(status=TrainingRunStatus.RUNNING).exists():
            return Response(
                {"detail": "A training run is already in progress. Please wait for it to finish."},
                status=status.HTTP_409_CONFLICT,
            )
        # Honestly flagged, not hidden: this check-then-create isn't
        # atomic (no DB-level advisory lock), so two requests arriving
        # within the same instant could both pass it. Accepted for this
        # batch - CELERY_TASK_ALWAYS_EAGER=True in this dev environment
        # (no real Celery worker pool - see config/settings.py's own
        # comment) means run_training_task actually finishes inline
        # before this view returns, so the window is effectively zero
        # here; a real async deployment closing this gap properly would
        # need a DB-level lock (e.g. select_for_update on a singleton row),
        # not just this existence check.

        try:
            df = training_module.load_and_validate_csv(uploaded_file)
            training_module.validate_minimum_rows(df)
        except training_module.MalformedDatasetError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        uploaded_file.seek(0)
        upload_dir = Path(settings.ML_DATASET_UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest_path = upload_dir / f"{uuid.uuid4().hex}_{uploaded_file.name}"
        with open(dest_path, "wb") as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)

        run = MLTrainingRun.objects.create(
            triggered_by=request.user,
            dataset_filename=uploaded_file.name,
            dataset_path=str(dest_path),
        )
        run_training_task.delay(run.pk, actor_id=request.user.pk, ip_address=get_client_ip(request))
        run.refresh_from_db()

        return Response(MLTrainingRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class MLTrainingRunListView(generics.ListAPIView):
    """F012 - training run history, for the ML Model Management dashboard."""

    permission_classes = [IsAdminRole]
    serializer_class = MLTrainingRunSerializer
    queryset = MLTrainingRun.objects.all()


class MLTrainingRunDetailView(generics.RetrieveAPIView):
    """F012 - poll a single training run's status/metrics."""

    permission_classes = [IsAdminRole]
    serializer_class = MLTrainingRunSerializer
    queryset = MLTrainingRun.objects.all()


class ProductionModelView(APIView):
    """ML batch 1: the production card on the ML Model Management page -
    which model buyers are served, its target and both R² values. Read-only."""

    permission_classes = [IsAdminRole]

    def get(self, request):
        production = ProductionModel.objects.select_related("training_run").filter(pk=1).first()
        if production is None:
            production = ProductionModel(pk=1)
        return Response(ProductionModelSerializer(production).data)


class MLTrainingRunDeployView(APIView):
    """Batch 6B - UC012 main flow steps 7-8: a SEPARATE, later, human-
    gated action from training+evaluation itself. apps.ml.tasks.
    run_training_task only marks a run `deploy_eligible` when it clears
    both deployment gates; this view is the only path that actually
    hot-swaps ProductionModel (via apps.ml.tasks.deploy_training_run).
    """

    permission_classes = [IsAdminRole]

    def post(self, request, pk):
        run = get_object_or_404(MLTrainingRun, pk=pk)

        # ML batch 1: a retired run stays in the history but never goes live.
        if run.retired_at is not None:
            return Response({"detail": RETIRED_RUN_MESSAGE}, status=status.HTTP_400_BAD_REQUEST)
        if run.deployed:
            return Response(
                {"detail": "This run has already been deployed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not run.deploy_eligible:
            return Response(
                {"detail": "This run is not eligible for deployment."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            deploy_training_run(run, actor=request.user, ip_address=get_client_ip(request))
        except (FileNotFoundError, OSError):
            # The candidate file this run pointed at is no longer on disk
            # (e.g. removed by the cleanup_ml_artifacts management
            # command before an admin got around to deploying it) - a
            # clean 400, never a raw 500, and nothing was mutated (the
            # file load happens before any write inside deploy_training_run).
            return Response(
                {"detail": "This run's candidate model file is no longer available. Please retrain."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(MLTrainingRunSerializer(run).data, status=status.HTTP_200_OK)
