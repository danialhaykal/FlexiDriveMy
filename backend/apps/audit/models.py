from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AuditActionCategory(models.TextChoices):
    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    ARCHIVE = "archive", "Archive"
    BULK_IMPORT = "bulk_import", "Bulk Import"
    # Run 1 fix batch 4 (UC013 "system runtime errors"): written by
    # apps.audit.services.log_runtime_error, never by an admin action.
    RUNTIME_ERROR = "runtime_error", "Runtime Error"


class AuditLog(models.Model):
    """Append-only record of an admin action against F010/F011 data.

    Immutability is enforced twice: here at the ORM level (save/delete raise
    once a row already has a pk) as a fast, friendly guard, and — the real
    guarantee — by a Postgres trigger added in migration 0002 that rejects
    any UPDATE/DELETE against this table outright, regardless of caller.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    # Denormalized so the log stays meaningful even if the actor's account
    # is later changed or removed.
    actor_email = models.CharField(max_length=254, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=20, choices=AuditActionCategory.choices)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=50, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    before_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    after_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp"]),
            models.Index(fields=["action"]),
            models.Index(fields=["actor"]),
            models.Index(fields=["resource_type"]),
        ]

    def __str__(self):
        return (
            f"{self.get_action_display()} {self.resource_type}#{self.resource_id} "
            f"by {self.actor_email or 'system'} at {self.timestamp}"
        )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("AuditLog rows are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog rows are append-only and cannot be deleted.")
