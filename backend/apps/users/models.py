from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower


class UserRole(models.TextChoices):
    USER = "user", "User"
    ADMIN = "admin", "Admin"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        # QA audit H7: BaseUserManager.normalize_email() only lowercases
        # the DOMAIN part (a deliberate Django default, since RFC 5321
        # technically allows a case-sensitive local-part) - that left
        # "QA.Tester@Example.com" stored as "QA.Tester@example.com",
        # still mismatched against a later "qa.tester@example.com"
        # registration/login. Every account's email is fully lowercased
        # at creation, so the DB's case-insensitive unique constraint
        # (migration 0002) is never actually hit in the normal create
        # path - only by something bypassing this manager entirely.
        email = email.strip().lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def get_by_natural_key(self, email):
        # Case-insensitive login lookup - without this, Django's
        # ModelBackend.authenticate() does an exact-match `.get(email=...)`
        # that would reject "qa.tester@example.com" against a stored
        # "QA.Tester@example.com", even though _create_user above now
        # always stores lowercase (this also covers any row that
        # predates this fix, e.g. an existing un-migrated dev DB).
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": email})

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.USER)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=10, choices=UserRole.choices, default=UserRole.USER)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["-date_joined"]
        constraints = [
            # Mirrors the real, currently-enforced DB constraint added
            # directly via AddConstraint in migration 0002_case_insensitive_
            # email.py - the model class never declared it, so Django's
            # migration state (replayed from migration files) disagreed
            # with the model's own declared state, and the next
            # `makemigrations users` would have proposed DROPPING it.
            # Declaring it here doesn't change what's in the database -
            # migration 0002 already did that - it just makes the model
            # describe what's already true.
            models.UniqueConstraint(Lower("email"), name="unique_lower_email"),
        ]

    def __str__(self):
        return self.email

    @property
    def is_admin_role(self):
        return self.role == UserRole.ADMIN

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    def get_short_name(self):
        return self.first_name or self.email
