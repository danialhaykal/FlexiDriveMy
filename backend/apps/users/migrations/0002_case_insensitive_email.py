from django.db import migrations, models
from django.db.models.functions import Lower

# QA audit H7: emails were case-sensitive end to end - registering
# "QA.Tester@Example.com" then logging in as "qa.tester@example.com" gave
# 401, and registering the lowercase variant afterward created a SECOND
# account for the same person (confirmed live: this dev DB already had
# exactly that pair - ids 3 "QA.Tester@example.com" and 4
# "qa.tester@example.com"). Fixed going forward by UserManager always
# lowercasing on create() and a case-insensitive lookup on login (see
# apps/users/models.py); this migration cleans up data created before
# that fix and adds the real DB-level guarantee a case-insensitive
# UniqueConstraint on Lower(email) can't both exist without colliding.


def merge_case_insensitive_duplicates(apps, schema_editor):
    User = apps.get_model("users", "User")

    groups = {}
    for user in User.objects.order_by("id"):
        groups.setdefault(user.email.lower(), []).append(user)

    for lower_email, users in groups.items():
        # Prefer a row that's ALREADY exactly lowercase as canonical - if
        # a lower-id row needed renaming to lower_email, that rename
        # would collide with this still-unique-at-the-time-of-this-
        # migration row at the DB level (the old plain unique=True on
        # email is still case-sensitive at this point in the migration).
        # Only when no row is already lowercase do we rename the
        # earliest-created one (safe: no collision possible there).
        canonical = next((user for user in users if user.email == lower_email), users[0])
        if canonical.email != lower_email:
            canonical.email = lower_email
            canonical.save(update_fields=["email"])

        for user in users:
            if user.id == canonical.id:
                continue
            # A duplicate account for the same person, differing only by
            # case - never hard-deleted (preserves FK integrity/
            # auditability for anything referencing this user). The new
            # UniqueConstraint(Lower("email")) added below applies across
            # ALL rows regardless of is_active, so merely deactivating it
            # would still collide with the canonical row on that index -
            # it also needs an email that can no longer collide, clearly
            # marked as a merged duplicate rather than reused.
            local_part, _, domain = lower_email.partition("@")
            user.email = f"{local_part}+duplicate-{user.id}@{domain}"
            user.is_active = False
            user.save(update_fields=["email", "is_active"])


def noop_reverse(apps, schema_editor):
    """Not reversible (which specific rows were deactivated/renamed isn't
    recorded) - a no-op reverse is acceptable here since this is a one-
    way data cleanup, not a feature toggle."""


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(merge_case_insensitive_duplicates, noop_reverse),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(Lower("email"), name="unique_lower_email"),
        ),
    ]
