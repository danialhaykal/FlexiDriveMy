from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel
from apps.vehicles.models import VehicleModel


class SavedScenario(TimeStampedModel):
    """F009 - UC009 Calculation History Save & Retrieval.

    `payload` is a frozen snapshot of the F005/F006/F007 results, so
    "reload the full comparison view" (UC009 step 7) reproduces what the
    user saw even if rates/residual ratios change later. Since run 1 fix
    batch 2 the SERVER builds it from the inputs (apps.scenarios.snapshot,
    snapshotVersion 2) - a client never sends figures. Older rows, built by
    the browser, are kept exactly as they were.
    `vehicle` is denormalized purely for a "My Comparisons" list view
    (name/thumbnail) without parsing the payload.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_scenarios")
    title = models.CharField(max_length=150)
    vehicle = models.ForeignKey(VehicleModel, on_delete=models.PROTECT, related_name="+")
    payload = models.JSONField()

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "title"], name="unique_scenario_title_per_user")
        ]

    def __str__(self):
        return f"{self.title} ({self.user.email})"
