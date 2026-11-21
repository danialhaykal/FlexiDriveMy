"""Run 3 fix batch 4 (F-12): `effective_from` is recorded and shown, but no
calculation schedules a row by it - every ACTIVE row is used today. A row dated in
the future would therefore take effect at once while saying otherwise, so a future
date is refused on every write path that edits these tables: the Django admin forms
(the only place they are edited) and their serializers. Rows already stored keep
their dates; only a new or changed date has to be today or earlier.

Kept off the model fields on purpose: a validator or help_text there would be a
migration, and the stored data does not change.
"""

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework import serializers

from .admin_forms import PlainConstraintMessagesForm

FUTURE_EFFECTIVE_FROM_MESSAGE = (
    "Scheduled (future-dated) policy rows are not supported; use today's date or earlier."
)


def effective_from_error(value):
    """The message when `value` is after today (Malaysia time), else None."""
    if value is not None and value > timezone.localdate():
        return FUTURE_EFFECTIVE_FROM_MESSAGE
    return None


class EffectiveFromNotFutureForm(PlainConstraintMessagesForm):
    """Base form for the Django admin of every policy table with effective_from
    (it also words a refused constraint plainly - Run 3 fix batch 5, F-14)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get("effective_from")
        if field is not None:
            field.help_text = FUTURE_EFFECTIVE_FROM_MESSAGE

    def clean_effective_from(self):
        value = self.cleaned_data.get("effective_from")
        message = effective_from_error(value)
        if message:
            raise ValidationError(message)
        return value


class EffectiveFromNotFutureSerializerMixin:
    """The same rule for a ModelSerializer of one of those tables."""

    def get_extra_kwargs(self):
        extra = super().get_extra_kwargs()
        extra.setdefault("effective_from", {}).setdefault("help_text", FUTURE_EFFECTIVE_FROM_MESSAGE)
        return extra

    def validate_effective_from(self, value):
        message = effective_from_error(value)
        if message:
            raise serializers.ValidationError(message)
        return value
