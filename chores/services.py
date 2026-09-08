from __future__ import annotations

import secrets
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import (
    AssignmentAudit,
    ChildProfile,
    Chore,
    ChoreRevision,
    EmailDelivery,
    FairnessSummary,
    Household,
    Invitation,
    Membership,
    Occurrence,
    ReassignmentRequest,
    ScheduledJob,
    User,
    WeeklyCapacity,
)


def next_week_start(day: date | None = None) -> date:
    day = day or timezone.localdate()
    return day + timedelta(days=7 - day.weekday())


def next_unassigned_week(household: Household, day: date | None = None) -> date:
    week_start = next_week_start(day)
    if Occurrence.objects.filter(
        household=household,
        due_date__range=(week_start, week_start + timedelta(days=6)),
    ).exists():
        week_start += timedelta(days=7)
    return week_start


def membership_for(user: User) -> Membership:
    try:
        membership = user.membership
    except Membership.DoesNotExist as exc:
        raise PermissionDenied("You do not belong to a household.") from exc
    if not membership.is_active:
        raise PermissionDenied("Your household membership is inactive.")
    return membership


def require_organizer(user: User) -> Membership:
    membership = membership_for(user)
    if not membership.is_organizer:
        raise PermissionDenied("Organizer access is required.")
    return membership


@transaction.atomic
def create_household(*, organizer: User, name: str, timezone_name: str) -> Household:
    if Membership.objects.filter(user=organizer).exists():
        raise ValidationError("A user can belong to only one household.")
    household = Household.objects.create(name=name, timezone=timezone_name)
    Membership.objects.create(
        household=household, user=organizer, role=Membership.Role.ORGANIZER
    )
    return household


@transaction.atomic
def create_invitation(
    *, organizer: User, email: str, role: str, valid_for: timedelta = timedelta(days=7)
) -> tuple[Invitation, str]:
    membership = require_organizer(organizer)
    if role not in Membership.Role.values:
        raise ValidationError("Choose a valid household role.")
    normalized_email = User.objects.normalize_email(email)
    if Membership.objects.filter(user__email__iexact=normalized_email).exists():
        raise ValidationError("That person already belongs to a household.")
    Invitation.objects.filter(
        household=membership.household,
        email__iexact=normalized_email,
        accepted_at__isnull=True,
    ).delete()
    token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        household=membership.household,
        email=normalized_email,
        role=role,
        token_digest=Invitation.digest_token(token),
        invited_by=organizer,
        expires_at=timezone.now() + valid_for,
    )
    return invitation, token


def invitation_for_token(token: str) -> Invitation:
    try:
        invitation = Invitation.objects.select_related("household").get(
            token_digest=Invitation.digest_token(token)
        )
    except Invitation.DoesNotExist as exc:
        raise ValidationError("This invitation is invalid.") from exc
    if not invitation.is_usable:
        raise ValidationError("This invitation has expired or was already used.")
    return invitation


@transaction.atomic
def accept_invitation(
    *, token: str, password: str, first_name: str = "", last_name: str = ""
) -> User:
    try:
        invitation = Invitation.objects.select_for_update().get(
            token_digest=Invitation.digest_token(token)
        )
    except Invitation.DoesNotExist as exc:
        raise ValidationError("This invitation is invalid.") from exc
    if not invitation.is_usable:
        raise ValidationError("This invitation has expired or was already used.")
    if Membership.objects.filter(user__email__iexact=invitation.email).exists():
        raise ValidationError("That user already belongs to a household.")

    user, created = User.objects.get_or_create(
        email=invitation.email,
        defaults={"first_name": first_name, "last_name": last_name},
    )
    if not created and user.has_usable_password():
        raise ValidationError("An account with this email already exists.")
    user.first_name = first_name or user.first_name
    user.last_name = last_name or user.last_name
    user.set_password(password)
    user.save()
    Membership.objects.create(
        household=invitation.household, user=user, role=invitation.role
    )
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    return user


def create_child(*, organizer: User, name: str) -> ChildProfile:
    membership = require_organizer(organizer)
    child = ChildProfile(household=membership.household, name=name)
    child.full_clean()
    child.save()
    return child


@transaction.atomic
def create_chore(*, actor: User, values: dict, today: date | None = None) -> Chore:
    membership = membership_for(actor)
    chore = Chore.objects.create(household=membership.household, created_by=actor)
    revision = ChoreRevision(
        chore=chore,
        effective_from=next_unassigned_week(membership.household, today),
        **values,
    )
    revision.full_clean()
    revision.save()
    return chore


@transaction.atomic
def revise_chore(
    *, chore: Chore, actor: User, values: dict, today: date | None = None
) -> ChoreRevision:
    membership = membership_for(actor)
    if chore.household_id != membership.household_id:
        raise PermissionDenied("This chore belongs to another household.")
    effective_from = next_unassigned_week(membership.household, today)
    revision = ChoreRevision(chore=chore, effective_from=effective_from, **values)
    revision.full_clean(exclude={"chore", "effective_from"})
    ChoreRevision.objects.filter(chore=chore, effective_from=effective_from).delete()
    revision.save()
    return revision


@transaction.atomic
def generate_occurrences(*, household: Household, week_start: date) -> list[Occurrence]:
    if week_start.weekday() != 0:
        raise ValidationError("week_start must be a Monday.")

    generated: list[Occurrence] = []
    for chore in household.chores.prefetch_related("revisions"):
        revision = (
            chore.revisions.filter(effective_from__lte=week_start)
            .order_by("-effective_from", "-pk")
            .first()
        )
        if revision is None or not revision.is_active:
            continue
        if revision.recurrence == ChoreRevision.Recurrence.DAILY:
            due_dates = [week_start + timedelta(days=offset) for offset in range(7)]
        else:
            due_dates = [week_start + timedelta(days=revision.due_weekday)]

        for due_date in due_dates:
            occurrence, _ = Occurrence.objects.get_or_create(
                chore=chore,
                due_date=due_date,
                defaults={
                    "household": household,
                    "revision": revision,
                    "estimated_minutes": revision.estimated_minutes,
                },
            )
            generated.append(occurrence)
    return generated


def mark_overdue_occurrences(
    *, as_of: date | None = None, household: Household | None = None
) -> int:
    as_of = as_of or timezone.localdate()
    occurrences = Occurrence.objects.filter(
        status=Occurrence.Status.PENDING, due_date__lt=as_of
    )
    if household:
        occurrences = occurrences.filter(household=household)
    return occurrences.update(status=Occurrence.Status.OVERDUE)


@transaction.atomic
def complete_occurrence(*, occurrence: Occurrence, actor: User, note: str = ""):
    membership = membership_for(actor)
    if occurrence.household_id != membership.household_id:
        raise PermissionDenied("This occurrence belongs to another household.")
    may_complete = occurrence.assigned_user_id == actor.id or (
        occurrence.assigned_child_id is not None and membership.is_organizer
    )
    if not may_complete:
        raise PermissionDenied("You cannot complete this occurrence.")
    if occurrence.status == Occurrence.Status.COMPLETED:
        return occurrence
    if len(note) > 280:
        raise ValidationError("Completion notes cannot exceed 280 characters.")
    occurrence.status = Occurrence.Status.COMPLETED
    occurrence.completed_at = timezone.now()
    occurrence.completed_by = actor
    occurrence.completion_note = note
    occurrence.save(
        update_fields=["status", "completed_at", "completed_by", "completion_note"]
    )
    return occurrence


def week_start_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


@transaction.atomic
def set_capacity(
    *, actor: User, week_start: date, level: str, child: ChildProfile | None = None
) -> WeeklyCapacity:
    membership = membership_for(actor)
    if week_start.weekday() != 0:
        raise ValidationError("week_start must be a Monday.")
    if level not in WeeklyCapacity.Level.values:
        raise ValidationError("Choose a valid capacity.")
    if child:
        require_organizer(actor)
        if child.household_id != membership.household_id or not child.is_active:
            raise PermissionDenied("That child is not active in your household.")
        lookup = {"child": child, "user": None}
    else:
        lookup = {"user": actor, "child": None}
    capacity, _ = WeeklyCapacity.objects.update_or_create(
        household=membership.household,
        week_start=week_start,
        **lookup,
        defaults={"level": level},
    )
    return capacity


def _participants(household: Household):
    adults = [
        ("user", membership.user)
        for membership in household.memberships.select_related("user")
        .filter(is_active=True, user__is_active=True)
        .order_by("user_id")
    ]
    children = [
        ("child", child)
        for child in household.children.filter(is_active=True).order_by("id")
    ]
    return adults + children


def _capacity_for(household, week_start, kind, person):
    lookup = {kind: person}
    return WeeklyCapacity.objects.filter(
        household=household, week_start=week_start, **lookup
    ).first()


def _previous_summary(household, week_start, kind, person):
    lookup = {kind: person}
    return FairnessSummary.objects.filter(
        household=household,
        week_start=week_start - timedelta(days=7),
        **lookup,
    ).first()


@transaction.atomic
def allocate_week(*, household: Household, week_start: date) -> list[Occurrence]:
    """Generate and assign a week, preserving prior assignments and overrides.

    Half of last week's target-to-assigned gap is carried forward, capped at 25%
    of this week's base target.  A stable greedy choice minimizes each assignee's
    resulting absolute deviation from their adjusted target.
    """
    occurrences = generate_occurrences(household=household, week_start=week_start)
    participants = _participants(household)
    if occurrences and not participants:
        raise ValidationError("The household has no active members.")

    total = sum(item.estimated_minutes for item in occurrences)
    details = {}
    total_weight = 0
    for kind, person in participants:
        capacity = _capacity_for(household, week_start, kind, person)
        level = capacity.level if capacity else WeeklyCapacity.Level.MEDIUM
        weight = WeeklyCapacity.WEIGHTS[level]
        details[(kind, person.pk)] = {
            "person": person,
            "level": level,
            "weight": weight,
        }
        total_weight += weight

    assigned = {key: 0 for key in details}
    for item in occurrences:
        if item.assigned_user_id and ("user", item.assigned_user_id) in assigned:
            assigned[("user", item.assigned_user_id)] += item.estimated_minutes
        elif item.assigned_child_id and ("child", item.assigned_child_id) in assigned:
            assigned[("child", item.assigned_child_id)] += item.estimated_minutes

    for key, detail in details.items():
        base = Decimal(total * detail["weight"]) / Decimal(total_weight or 1)
        previous = _previous_summary(household, week_start, key[0], detail["person"])
        carry = Decimal("0")
        if previous:
            gap = previous.adjusted_target_minutes - Decimal(previous.assigned_minutes)
            raw_carry = gap * Decimal("0.5")
            bound = base * Decimal("0.25")
            carry = max(-bound, min(bound, raw_carry))
        detail["base"] = base
        detail["target"] = max(Decimal("0"), base + carry)

    for item in sorted(
        occurrences, key=lambda value: (value.due_date, value.chore_id, value.pk)
    ):
        if item.assigned_user_id or item.assigned_child_id:
            continue
        eligible = [
            key for key in details if key[0] == "user" or item.revision.child_eligible
        ]
        if not eligible:
            raise ValidationError(f"No eligible assignee for {item.revision.name}.")
        chosen = min(
            eligible,
            key=lambda key: (
                abs(
                    Decimal(assigned[key] + item.estimated_minutes)
                    - details[key]["target"]
                )
                - abs(Decimal(assigned[key]) - details[key]["target"]),
                assigned[key] - float(details[key]["target"]),
                0 if key[0] == "user" else 1,
                key[1],
            ),
        )
        setattr(item, f"assigned_{chosen[0]}", details[chosen]["person"])
        item.full_clean()
        item.save(update_fields=[f"assigned_{chosen[0]}"])
        assigned[chosen] += item.estimated_minutes

    for key, detail in details.items():
        lookup = {
            key[0]: detail["person"],
            "household": household,
            "week_start": week_start,
        }
        FairnessSummary.objects.update_or_create(
            **lookup,
            defaults={
                "capacity_level": detail["level"],
                "base_target_minutes": detail["base"],
                "adjusted_target_minutes": detail["target"],
                "assigned_minutes": assigned[key],
            },
        )
    return occurrences


def _eligible_replacement(occurrence, *, user=None, child=None):
    if (user is None) == (child is None):
        raise ValidationError("Choose exactly one replacement.")
    if user:
        membership = getattr(user, "membership", None)
        if (
            not membership
            or membership.household_id != occurrence.household_id
            or not membership.is_active
            or not user.is_active
        ):
            raise ValidationError("Choose an active adult in this household.")
    if child and (
        child.household_id != occurrence.household_id
        or not child.is_active
        or not occurrence.revision.child_eligible
    ):
        raise ValidationError("That child is not eligible for this chore.")


@transaction.atomic
def request_reassignment(*, occurrence: Occurrence, actor: User, reason: str = ""):
    membership = membership_for(actor)
    if occurrence.household_id != membership.household_id:
        raise PermissionDenied("This occurrence belongs to another household.")
    if occurrence.assigned_user_id != actor.id:
        raise PermissionDenied("You may request reassignment only for your own chore.")
    if occurrence.status == Occurrence.Status.COMPLETED:
        raise ValidationError("A completed chore cannot be reassigned.")
    if len(reason) > 280:
        raise ValidationError("Reasons cannot exceed 280 characters.")
    request, created = ReassignmentRequest.objects.get_or_create(
        occurrence=occurrence,
        status=ReassignmentRequest.Status.PENDING,
        defaults={"requested_by": actor, "reason": reason},
    )
    return request


def _update_summary_after_assignment(occurrence, previous_user, previous_child):
    week_start = week_start_for(occurrence.due_date)
    for kind, person, change in (
        ("user", previous_user, -occurrence.estimated_minutes),
        ("child", previous_child, -occurrence.estimated_minutes),
        ("user", occurrence.assigned_user, occurrence.estimated_minutes),
        ("child", occurrence.assigned_child, occurrence.estimated_minutes),
    ):
        if person:
            summary = FairnessSummary.objects.filter(
                household=occurrence.household, week_start=week_start, **{kind: person}
            ).first()
            if summary:
                summary.assigned_minutes = max(0, summary.assigned_minutes + change)
                summary.save(update_fields=["assigned_minutes"])


@transaction.atomic
def override_assignment(
    *,
    occurrence: Occurrence,
    actor: User,
    user=None,
    child=None,
    reason: str = "",
    kind: str = AssignmentAudit.Kind.OVERRIDE,
):
    membership = require_organizer(actor)
    if occurrence.household_id != membership.household_id:
        raise PermissionDenied("This occurrence belongs to another household.")
    if occurrence.status == Occurrence.Status.COMPLETED:
        raise ValidationError("A completed chore cannot be reassigned.")
    if len(reason) > 280:
        raise ValidationError("Reasons cannot exceed 280 characters.")
    _eligible_replacement(occurrence, user=user, child=child)
    previous_user, previous_child = occurrence.assigned_user, occurrence.assigned_child
    occurrence.assigned_user, occurrence.assigned_child = user, child
    occurrence.full_clean()
    occurrence.save(update_fields=["assigned_user", "assigned_child"])
    audit = AssignmentAudit.objects.create(
        occurrence=occurrence,
        kind=kind,
        actor=actor,
        previous_user=previous_user,
        previous_child=previous_child,
        new_user=user,
        new_child=child,
        reason=reason,
    )
    _update_summary_after_assignment(occurrence, previous_user, previous_child)
    return audit


@transaction.atomic
def decide_reassignment(
    *,
    request: ReassignmentRequest,
    actor: User,
    approve: bool,
    user=None,
    child=None,
    reason: str = "",
):
    require_organizer(actor)
    request = (
        ReassignmentRequest.objects.select_for_update()
        .select_related("occurrence")
        .get(pk=request.pk)
    )
    if request.occurrence.household_id != actor.membership.household_id:
        raise PermissionDenied("This request belongs to another household.")
    if request.status != ReassignmentRequest.Status.PENDING:
        raise ValidationError("This request has already been decided.")
    if approve:
        override_assignment(
            occurrence=request.occurrence,
            actor=actor,
            user=user,
            child=child,
            reason=reason or request.reason,
            kind=AssignmentAudit.Kind.REASSIGNMENT,
        )
        request.status = ReassignmentRequest.Status.APPROVED
    else:
        request.status = ReassignmentRequest.Status.REJECTED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.save(update_fields=["status", "decided_by", "decided_at"])
    return request


def _organizer_emails(household):
    return list(
        household.memberships.filter(
            role=Membership.Role.ORGANIZER, is_active=True, user__is_active=True
        ).values_list("user__email", flat=True)
    )


def _deliver(*, key, household, kind, recipient, subject, body, occurrence=None):
    delivery, _ = EmailDelivery.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "household": household,
            "occurrence": occurrence,
            "kind": kind,
            "recipient": recipient,
        },
    )
    if delivery.sent_at:
        return delivery
    delivery.attempts += 1
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient])
    except Exception as exc:
        delivery.last_error = str(exc)
        delivery.save(update_fields=["attempts", "last_error"])
        raise
    delivery.sent_at = timezone.now()
    delivery.last_error = ""
    delivery.save(update_fields=["attempts", "sent_at", "last_error"])
    return delivery


def send_assignment_emails(*, household: Household, week_start: date):
    occurrences = Occurrence.objects.filter(
        household=household,
        due_date__range=(week_start, week_start + timedelta(days=6)),
    ).select_related("assigned_user", "assigned_child", "revision")
    adult_ids = set(
        occurrences.exclude(assigned_user=None).values_list(
            "assigned_user_id", flat=True
        )
    )
    for user in User.objects.filter(id__in=adult_ids):
        names = [
            item.revision.name
            for item in occurrences
            if item.assigned_user_id == user.id
        ]
        _deliver(
            key=f"assignment:{household.pk}:{week_start}:{user.email.lower()}",
            household=household,
            kind=EmailDelivery.Kind.ASSIGNMENT,
            recipient=user.email,
            subject=f"Your chores for {week_start}",
            body="Your assigned chores:\n" + "\n".join(f"- {name}" for name in names),
        )
    child_items = [item for item in occurrences if item.assigned_child_id]
    if child_items:
        body = "Child assignments:\n" + "\n".join(
            f"- {item.assigned_child.name}: {item.revision.name}"
            for item in child_items
        )
        for email in _organizer_emails(household):
            _deliver(
                key=f"assignment-child:{household.pk}:{week_start}:{email.lower()}",
                household=household,
                kind=EmailDelivery.Kind.ASSIGNMENT,
                recipient=email,
                subject=f"Child chores for {week_start}",
                body=body,
            )


def send_due_reminders(*, household: Household, due_date: date):
    occurrences = (
        Occurrence.objects.filter(
            household=household,
            due_date=due_date,
        )
        .exclude(status=Occurrence.Status.COMPLETED)
        .select_related("assigned_user", "assigned_child", "revision")
    )
    organizer_emails = _organizer_emails(household)
    for item in occurrences:
        recipients = (
            [item.assigned_user.email] if item.assigned_user else organizer_emails
        )
        for email in recipients:
            _deliver(
                key=f"reminder:{item.pk}:{email.lower()}",
                household=household,
                occurrence=item,
                kind=EmailDelivery.Kind.REMINDER,
                recipient=email,
                subject=f"Chore due today: {item.revision.name}",
                body=f"{item.revision.name} is due today ({due_date}).",
            )


def enqueue_scheduled_jobs(*, now=None) -> int:
    now = now or timezone.now()
    created = 0
    for household in Household.objects.all():
        local_now = now.astimezone(ZoneInfo(household.timezone))
        local_day = local_now.date()
        jobs = [
            (ScheduledJob.Kind.OVERDUE, local_day),
        ]
        if local_now.time() >= household.reminder_time:
            jobs.append((ScheduledJob.Kind.REMIND, local_day))
        if local_day.weekday() == 6 and local_now.hour >= 18:
            jobs.append((ScheduledJob.Kind.ALLOCATE, local_day + timedelta(days=1)))
        for kind, target in jobs:
            _, was_created = ScheduledJob.objects.get_or_create(
                idempotency_key=f"{kind}:{household.pk}:{target}",
                defaults={
                    "household": household,
                    "kind": kind,
                    "target_date": target,
                    "run_at": now,
                },
            )
            created += int(was_created)
    return created


def run_pending_jobs(*, now=None) -> int:
    now = now or timezone.now()
    completed = 0
    for job in (
        ScheduledJob.objects.filter(completed_at=None, run_at__lte=now)
        .select_related("household")
        .order_by("run_at", "pk")
    ):
        job.attempts += 1
        try:
            if job.kind == ScheduledJob.Kind.ALLOCATE:
                allocate_week(household=job.household, week_start=job.target_date)
                send_assignment_emails(
                    household=job.household, week_start=job.target_date
                )
            elif job.kind == ScheduledJob.Kind.REMIND:
                send_due_reminders(household=job.household, due_date=job.target_date)
            else:
                mark_overdue_occurrences(as_of=job.target_date, household=job.household)
        except Exception as exc:
            job.last_error = str(exc)
            job.save(update_fields=["attempts", "last_error"])
            continue
        job.completed_at = timezone.now()
        job.last_error = ""
        job.save(update_fields=["attempts", "completed_at", "last_error"])
        completed += 1
    return completed
