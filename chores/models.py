from __future__ import annotations

import hashlib

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff and is_superuser enabled")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    def __str__(self) -> str:
        return self.email

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self) -> str:
        return self.first_name or self.email


class Household(models.Model):
    name = models.CharField(max_length=120)
    timezone = models.CharField(max_length=64, default="UTC")
    reminder_time = models.TimeField(default="09:00")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        MEMBER = "member", "Adult member"
        ORGANIZER = "organizer", "Organizer"

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="membership"
    )
    role = models.CharField(max_length=16, choices=Role, default=Role.MEMBER)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user} in {self.household}"

    @property
    def is_organizer(self) -> bool:
        return self.role == self.Role.ORGANIZER


class ChildProfile(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="children"
    )
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_child_name_per_household"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Invitation(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=16, choices=Membership.Role, default=Membership.Role.MEMBER
    )
    token_digest = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="sent_invitations"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "email"],
                condition=Q(accepted_at__isnull=True),
                name="one_pending_invitation_per_email",
            )
        ]

    @staticmethod
    def digest_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @property
    def is_usable(self) -> bool:
        return self.accepted_at is None and self.expires_at > timezone.now()


class Chore(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="chores"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_chores"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        revision = self.revisions.order_by("-effective_from").first()
        return revision.name if revision else f"Chore {self.pk}"


class ChoreRevision(models.Model):
    class Recurrence(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"

    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name="revisions")
    effective_from = models.DateField()
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, max_length=1000)
    estimated_minutes = models.PositiveSmallIntegerField()
    recurrence = models.CharField(max_length=8, choices=Recurrence)
    due_weekday = models.PositiveSmallIntegerField(null=True, blank=True)
    child_eligible = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["chore", "effective_from"],
                name="one_chore_revision_per_effective_date",
            ),
            models.CheckConstraint(
                condition=Q(estimated_minutes__gt=0),
                name="chore_effort_is_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(recurrence="daily", due_weekday__isnull=True)
                    | Q(
                        recurrence="weekly",
                        due_weekday__gte=0,
                        due_weekday__lte=6,
                    )
                ),
                name="chore_recurrence_has_valid_weekday",
            ),
        ]

    def clean(self) -> None:
        if self.recurrence == self.Recurrence.DAILY and self.due_weekday is not None:
            raise ValidationError({"due_weekday": "Daily chores do not use a weekday."})
        if self.recurrence == self.Recurrence.WEEKLY and self.due_weekday is None:
            raise ValidationError({"due_weekday": "Choose a weekday."})

    def __str__(self) -> str:
        return f"{self.name} from {self.effective_from}"


class Occurrence(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        OVERDUE = "overdue", "Overdue"
        COMPLETED = "completed", "Completed"

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="occurrences"
    )
    chore = models.ForeignKey(
        Chore, on_delete=models.PROTECT, related_name="occurrences"
    )
    revision = models.ForeignKey(
        ChoreRevision, on_delete=models.PROTECT, related_name="occurrences"
    )
    due_date = models.DateField()
    estimated_minutes = models.PositiveSmallIntegerField()
    assigned_user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assigned_occurrences",
    )
    assigned_child = models.ForeignKey(
        ChildProfile,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assigned_occurrences",
    )
    status = models.CharField(max_length=12, choices=Status, default=Status.PENDING)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="recorded_completions",
    )
    completion_note = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["chore", "due_date"], name="one_occurrence_per_chore_due_date"
            ),
            models.CheckConstraint(
                condition=~(
                    Q(assigned_user__isnull=False) & Q(assigned_child__isnull=False)
                ),
                name="occurrence_has_at_most_one_assignee",
            ),
            models.CheckConstraint(
                condition=Q(estimated_minutes__gt=0),
                name="occurrence_effort_is_positive",
            ),
        ]

    def clean(self) -> None:
        if self.chore_id and self.household_id != self.chore.household_id:
            raise ValidationError("Occurrence and chore must belong to one household.")
        if self.revision_id and self.revision.chore_id != self.chore_id:
            raise ValidationError("Occurrence revision must belong to its chore.")
        if self.assigned_user_id:
            membership = getattr(self.assigned_user, "membership", None)
            if not membership or membership.household_id != self.household_id:
                raise ValidationError("Adult assignee must belong to the household.")
        if (
            self.assigned_child_id
            and self.assigned_child.household_id != self.household_id
        ):
            raise ValidationError("Child assignee must belong to the household.")
        if self.assigned_child_id and not self.revision.child_eligible:
            raise ValidationError("This chore is not child-eligible.")

    def __str__(self) -> str:
        return f"{self.revision.name} due {self.due_date}"


class WeeklyCapacity(models.Model):
    class Level(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    WEIGHTS = {Level.LOW: 1, Level.MEDIUM: 2, Level.HIGH: 3}

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="weekly_capacities"
    )
    week_start = models.DateField()
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.CASCADE, related_name="capacities"
    )
    child = models.ForeignKey(
        ChildProfile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="capacities",
    )
    level = models.CharField(max_length=8, choices=Level, default=Level.MEDIUM)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(user__isnull=False, child__isnull=True)
                    | Q(user__isnull=True, child__isnull=False)
                ),
                name="capacity_has_exactly_one_member",
            ),
            models.UniqueConstraint(
                fields=["week_start", "user"],
                condition=Q(user__isnull=False),
                name="one_capacity_per_adult_week",
            ),
            models.UniqueConstraint(
                fields=["week_start", "child"],
                condition=Q(child__isnull=False),
                name="one_capacity_per_child_week",
            ),
        ]

    @property
    def weight(self) -> int:
        return self.WEIGHTS[self.level]


class FairnessSummary(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="fairness_summaries"
    )
    week_start = models.DateField()
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.CASCADE, related_name="fairness"
    )
    child = models.ForeignKey(
        ChildProfile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="fairness",
    )
    capacity_level = models.CharField(max_length=8, choices=WeeklyCapacity.Level)
    base_target_minutes = models.DecimalField(max_digits=8, decimal_places=2)
    adjusted_target_minutes = models.DecimalField(max_digits=8, decimal_places=2)
    assigned_minutes = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(user__isnull=False, child__isnull=True)
                    | Q(user__isnull=True, child__isnull=False)
                ),
                name="fairness_has_exactly_one_member",
            ),
            models.UniqueConstraint(
                fields=["week_start", "user"],
                condition=Q(user__isnull=False),
                name="one_fairness_summary_per_adult_week",
            ),
            models.UniqueConstraint(
                fields=["week_start", "child"],
                condition=Q(child__isnull=False),
                name="one_fairness_summary_per_child_week",
            ),
        ]


class ReassignmentRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    occurrence = models.ForeignKey(
        Occurrence, on_delete=models.CASCADE, related_name="reassignment_requests"
    )
    requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="reassignment_requests"
    )
    reason = models.CharField(max_length=280, blank=True)
    status = models.CharField(max_length=10, choices=Status, default=Status.PENDING)
    decided_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reassignment_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["occurrence"],
                condition=Q(status="pending"),
                name="one_pending_reassignment_per_occurrence",
            )
        ]


class AssignmentAudit(models.Model):
    class Kind(models.TextChoices):
        REASSIGNMENT = "reassignment", "Approved reassignment"
        OVERRIDE = "override", "Organizer override"

    occurrence = models.ForeignKey(
        Occurrence, on_delete=models.PROTECT, related_name="assignment_audits"
    )
    kind = models.CharField(max_length=16, choices=Kind)
    actor = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="assignment_audits"
    )
    previous_user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    previous_child = models.ForeignKey(
        ChildProfile, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    new_user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    new_child = models.ForeignKey(
        ChildProfile, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reason = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EmailDelivery(models.Model):
    class Kind(models.TextChoices):
        ASSIGNMENT = "assignment", "Weekly assignment"
        REMINDER = "reminder", "Due-day reminder"

    idempotency_key = models.CharField(max_length=255, unique=True)
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="email_deliveries"
    )
    occurrence = models.ForeignKey(
        Occurrence,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="email_deliveries",
    )
    kind = models.CharField(max_length=12, choices=Kind)
    recipient = models.EmailField()
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ScheduledJob(models.Model):
    class Kind(models.TextChoices):
        ALLOCATE = "allocate", "Allocate week"
        REMIND = "remind", "Send due-day reminders"
        OVERDUE = "overdue", "Mark overdue"

    idempotency_key = models.CharField(max_length=255, unique=True)
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="scheduled_jobs"
    )
    kind = models.CharField(max_length=12, choices=Kind)
    run_at = models.DateTimeField()
    target_date = models.DateField()
    attempts = models.PositiveSmallIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
