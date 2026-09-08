from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from chores.forms import AssignmentForm, ReassignmentDecisionForm
from chores.models import (
    AssignmentAudit,
    ChildProfile,
    ChoreRevision,
    EmailDelivery,
    FairnessSummary,
    Occurrence,
    ReassignmentRequest,
    ScheduledJob,
    WeeklyCapacity,
)
from chores.services import (
    allocate_week,
    decide_reassignment,
    enqueue_scheduled_jobs,
    override_assignment,
    request_reassignment,
    run_pending_jobs,
    send_assignment_emails,
    send_due_reminders,
    set_capacity,
)

pytestmark = pytest.mark.django_db

MONDAY = date(2026, 9, 7)


def values(**overrides):
    result = {
        "name": "Dishes",
        "description": "",
        "estimated_minutes": 20,
        "recurrence": ChoreRevision.Recurrence.DAILY,
        "due_weekday": None,
        "child_eligible": False,
        "is_active": True,
    }
    result.update(overrides)
    return result


def make_chore(actor, **overrides):
    from chores.services import create_chore

    return create_chore(
        actor=actor, values=values(**overrides), today=MONDAY - timedelta(days=1)
    )


def make_occurrence(actor, *, assignee=None, child=None, child_eligible=False):
    chore = make_chore(
        actor, recurrence="weekly", due_weekday=0, child_eligible=child_eligible
    )
    return Occurrence.objects.create(
        household=actor.membership.household,
        chore=chore,
        revision=chore.revisions.get(),
        due_date=MONDAY,
        estimated_minutes=20,
        assigned_user=assignee,
        assigned_child=child,
    )


def test_capacity_permissions_validation_and_weight(organizer, member, outsider):
    capacity = set_capacity(
        actor=member, week_start=MONDAY, level=WeeklyCapacity.Level.HIGH
    )
    assert capacity.weight == 3
    assert (
        set_capacity(
            actor=member, week_start=MONDAY, level=WeeklyCapacity.Level.LOW
        ).level
        == WeeklyCapacity.Level.LOW
    )
    child = ChildProfile.objects.create(
        household=organizer.membership.household, name="Ari"
    )
    child_capacity = set_capacity(
        actor=organizer,
        child=child,
        week_start=MONDAY,
        level=WeeklyCapacity.Level.MEDIUM,
    )
    assert child_capacity.child == child
    with pytest.raises(PermissionDenied):
        set_capacity(actor=member, child=child, week_start=MONDAY, level="low")
    with pytest.raises(PermissionDenied):
        set_capacity(
            actor=organizer,
            child=ChildProfile.objects.create(
                household=outsider.membership.household, name="Other"
            ),
            week_start=MONDAY,
            level="low",
        )
    with pytest.raises(ValidationError, match="Monday"):
        set_capacity(actor=member, week_start=MONDAY + timedelta(days=1), level="low")
    with pytest.raises(ValidationError, match="valid capacity"):
        set_capacity(actor=member, week_start=MONDAY, level="enormous")


def test_allocator_is_weighted_eligible_deterministic_and_preserves_assignments(
    organizer, member
):
    child = ChildProfile.objects.create(
        household=organizer.membership.household, name="Ari"
    )
    make_chore(organizer, name="Adult work", estimated_minutes=30)
    make_chore(organizer, name="Child work", estimated_minutes=10, child_eligible=True)
    set_capacity(actor=organizer, week_start=MONDAY, level="high")
    set_capacity(actor=member, week_start=MONDAY, level="low")
    set_capacity(actor=organizer, child=child, week_start=MONDAY, level="low")

    items = allocate_week(household=organizer.membership.household, week_start=MONDAY)
    first_assignments = [
        (item.pk, item.assigned_user_id, item.assigned_child_id) for item in items
    ]
    assert all(
        item.assigned_child_id is None
        for item in items
        if not item.revision.child_eligible
    )
    assert FairnessSummary.objects.get(user=organizer).assigned_minutes > 0

    allocate_week(household=organizer.membership.household, week_start=MONDAY)
    assert sorted(first_assignments) == sorted(
        Occurrence.objects.filter(household=organizer.membership.household).values_list(
            "id", "assigned_user_id", "assigned_child_id"
        )
    )


def test_allocator_applies_bounded_previous_week_compensation(organizer, member):
    make_chore(organizer, recurrence="weekly", due_weekday=0, estimated_minutes=100)
    previous = MONDAY - timedelta(days=7)
    FairnessSummary.objects.create(
        household=organizer.membership.household,
        week_start=previous,
        user=organizer,
        capacity_level="medium",
        base_target_minutes=50,
        adjusted_target_minutes=100,
        assigned_minutes=0,
    )
    allocate_week(household=organizer.membership.household, week_start=MONDAY)
    summary = FairnessSummary.objects.get(user=organizer, week_start=MONDAY)
    assert summary.base_target_minutes == Decimal("50")
    assert summary.adjusted_target_minutes == Decimal("62.5")


def test_allocator_rejects_household_without_active_members(organizer):
    make_chore(organizer)
    organizer.membership.is_active = False
    organizer.membership.save(update_fields=["is_active"])
    with pytest.raises(ValidationError, match="no active members"):
        allocate_week(household=organizer.membership.household, week_start=MONDAY)


def test_reassignment_and_override_are_audited_and_update_fairness(
    organizer, member, outsider
):
    occurrence = make_occurrence(organizer, assignee=member)
    for user, assigned in ((organizer, 0), (member, 20)):
        FairnessSummary.objects.create(
            household=organizer.membership.household,
            week_start=MONDAY,
            user=user,
            capacity_level="medium",
            base_target_minutes=10,
            adjusted_target_minutes=10,
            assigned_minutes=assigned,
        )
    reassignment = request_reassignment(
        occurrence=occurrence, actor=member, reason="Travel"
    )
    assert request_reassignment(occurrence=occurrence, actor=member) == reassignment
    decision = decide_reassignment(
        request=reassignment, actor=organizer, approve=True, user=organizer
    )
    occurrence.refresh_from_db()
    assert decision.status == ReassignmentRequest.Status.APPROVED
    assert occurrence.assigned_user == organizer
    audit = AssignmentAudit.objects.get()
    assert audit.kind == AssignmentAudit.Kind.REASSIGNMENT
    assert audit.previous_user == member
    assert FairnessSummary.objects.get(user=organizer).assigned_minutes == 20
    assert FairnessSummary.objects.get(user=member).assigned_minutes == 0
    with pytest.raises(ValidationError, match="already been decided"):
        decide_reassignment(request=reassignment, actor=organizer, approve=False)
    with pytest.raises(PermissionDenied):
        override_assignment(occurrence=occurrence, actor=outsider, user=outsider)


def test_reassignment_rejection_and_invalid_requests(organizer, member):
    occurrence = make_occurrence(organizer, assignee=organizer)
    with pytest.raises(PermissionDenied):
        request_reassignment(occurrence=occurrence, actor=member)
    occurrence.assigned_user = member
    occurrence.save(update_fields=["assigned_user"])
    reassignment = request_reassignment(occurrence=occurrence, actor=member)
    decide_reassignment(request=reassignment, actor=organizer, approve=False)
    assert not AssignmentAudit.objects.exists()
    occurrence.status = Occurrence.Status.COMPLETED
    occurrence.save(update_fields=["status"])
    with pytest.raises(ValidationError, match="completed"):
        request_reassignment(occurrence=occurrence, actor=member)
    with pytest.raises(ValidationError, match="completed"):
        override_assignment(occurrence=occurrence, actor=organizer, user=organizer)


def test_override_validates_replacement_and_child_eligibility(organizer, outsider):
    occurrence = make_occurrence(organizer, assignee=organizer)
    child = ChildProfile.objects.create(
        household=organizer.membership.household, name="Ari"
    )
    with pytest.raises(ValidationError, match="exactly one"):
        override_assignment(occurrence=occurrence, actor=organizer)
    with pytest.raises(ValidationError, match="active adult"):
        override_assignment(occurrence=occurrence, actor=organizer, user=outsider)
    with pytest.raises(ValidationError, match="not eligible"):
        override_assignment(occurrence=occurrence, actor=organizer, child=child)
    with pytest.raises(ValidationError, match="280"):
        override_assignment(
            occurrence=occurrence, actor=organizer, user=organizer, reason="x" * 281
        )


@pytest.mark.django_db
def test_assignment_and_reminder_email_are_idempotent(settings, organizer, member):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    child = ChildProfile.objects.create(
        household=organizer.membership.household, name="Ari"
    )
    adult_item = make_occurrence(organizer, assignee=member)
    child_item = make_occurrence(organizer, child=child, child_eligible=True)
    send_assignment_emails(household=organizer.membership.household, week_start=MONDAY)
    send_assignment_emails(household=organizer.membership.household, week_start=MONDAY)
    assert len(mail.outbox) == 2
    send_due_reminders(household=organizer.membership.household, due_date=MONDAY)
    send_due_reminders(household=organizer.membership.household, due_date=MONDAY)
    assert len(mail.outbox) == 4
    assert EmailDelivery.objects.count() == 4
    adult_item.status = Occurrence.Status.COMPLETED
    adult_item.save(update_fields=["status"])
    assert child_item.assigned_child == child


def test_email_failure_is_recorded_and_retried(organizer, member):
    make_occurrence(organizer, assignee=member)
    with patch("chores.services.send_mail", side_effect=RuntimeError("smtp down")):
        with pytest.raises(RuntimeError):
            send_due_reminders(
                household=organizer.membership.household, due_date=MONDAY
            )
    delivery = EmailDelivery.objects.get()
    assert delivery.attempts == 1
    assert delivery.last_error == "smtp down"


def test_scheduler_enqueues_timezone_jobs_and_executes_once(settings, organizer):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    organizer.membership.household.timezone = "America/Los_Angeles"
    organizer.membership.household.reminder_time = time(9)
    organizer.membership.household.save(update_fields=["timezone", "reminder_time"])
    make_chore(organizer, recurrence="weekly", due_weekday=0)
    sunday = datetime(2026, 9, 6, 19, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert enqueue_scheduled_jobs(now=sunday) == 3
    assert enqueue_scheduled_jobs(now=sunday) == 0
    assert run_pending_jobs(now=sunday) == 3
    assert run_pending_jobs(now=sunday) == 0
    assert ScheduledJob.objects.filter(completed_at__isnull=False).count() == 3
    assert Occurrence.objects.filter(due_date=MONDAY).exists()


def test_scheduler_records_failure_and_command_runs_once(organizer):
    job = ScheduledJob.objects.create(
        idempotency_key="bad",
        household=organizer.membership.household,
        kind=ScheduledJob.Kind.ALLOCATE,
        run_at=timezone.now() - timedelta(minutes=1),
        target_date=MONDAY + timedelta(days=1),
    )
    assert run_pending_jobs() == 0
    job.refresh_from_db()
    assert job.attempts == 1 and "Monday" in job.last_error
    output = StringIO()
    call_command("run_scheduler", once=True, stdout=output)
    assert "Enqueued" in output.getvalue()


def test_forms_limit_children_to_eligible_chores(organizer, member):
    child = ChildProfile.objects.create(
        household=organizer.membership.household, name="Ari"
    )
    occurrence = make_occurrence(organizer, assignee=member)
    form = AssignmentForm(
        household=organizer.membership.household, occurrence=occurrence
    )
    assert (f"child:{child.id}", child.name) not in form.fields["assignee"].choices
    decision = ReassignmentDecisionForm(
        {"decision": "reject", "reason": "No", "assignee": ""},
        household=organizer.membership.household,
        occurrence=occurrence,
    )
    assert decision.is_valid()


def test_capacity_reassignment_and_override_views(client, organizer, member):
    occurrence = make_occurrence(organizer, assignee=member)
    client.force_login(member)
    response = client.post(reverse("chores:capacity-update"), {"level": "high"})
    assert response.status_code == 302
    response = client.post(
        reverse("chores:reassignment-request", args=[occurrence.id]),
        {"reason": "Busy"},
    )
    assert response.status_code == 302
    reassignment = ReassignmentRequest.objects.get()

    client.force_login(organizer)
    response = client.post(
        reverse("chores:reassignment-decide", args=[reassignment.id]),
        {"decision": "reject", "assignee": "", "reason": "Later"},
    )
    assert response.status_code == 302
    response = client.post(
        reverse("chores:occurrence-override", args=[occurrence.id]),
        {"assignee": f"user:{organizer.id}", "reason": "Balance"},
    )
    assert response.status_code == 302
    assert AssignmentAudit.objects.filter(kind=AssignmentAudit.Kind.OVERRIDE).exists()


def test_outsiders_cannot_use_adjustment_views(client, organizer, member, outsider):
    occurrence = make_occurrence(organizer, assignee=member)
    reassignment = request_reassignment(occurrence=occurrence, actor=member)
    client.force_login(outsider)
    assert (
        client.get(
            reverse("chores:reassignment-request", args=[occurrence.id])
        ).status_code
        == 404
    )
    assert (
        client.get(
            reverse("chores:reassignment-decide", args=[reassignment.id])
        ).status_code
        == 404
    )
    assert (
        client.get(
            reverse("chores:occurrence-override", args=[occurrence.id])
        ).status_code
        == 404
    )


def test_database_rejects_capacity_without_member(organizer):
    with pytest.raises(IntegrityError):
        WeeklyCapacity.objects.create(
            household=organizer.membership.household,
            week_start=MONDAY,
            level="medium",
        )
