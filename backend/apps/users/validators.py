"""Run 3 fix batch 5 (F-05): one phone-number rule for registration and the
profile update (the only two places a user types it).

Allowed: digits, spaces, "+", "-" and parentheses, 7 to 20 characters, with at
least 7 digits (so "call-me" or "(((((((" are refused). Blank stays allowed - the
phone number is optional. Kept off the model field on purpose: a validator there
would be a migration, and stored data is not changed. The serializers turn off
their own max-length check for this field so a long number gets this one
sentence (20 is still the most, here and in the database column).
"""

import re

from rest_framework import serializers

PHONE_NUMBER_MESSAGE = "Enter a valid phone number, for example +60 12-345 6789."
_ALLOWED = re.compile(r"^[0-9+\-() ]{7,20}$")
MIN_DIGITS = 7


def validate_phone_number(value):
    if not value:
        return value
    if not _ALLOWED.match(value) or sum(ch.isdigit() for ch in value) < MIN_DIGITS:
        raise serializers.ValidationError(PHONE_NUMBER_MESSAGE)
    return value
