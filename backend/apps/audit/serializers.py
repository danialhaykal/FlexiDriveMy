from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_id = serializers.IntegerField(source="actor.id", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor_id",
            "actor_email",
            "timestamp",
            "action",
            "resource_type",
            "resource_id",
            "ip_address",
            "before_data",
            "after_data",
        ]
        read_only_fields = fields
