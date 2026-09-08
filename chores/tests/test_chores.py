from datetime import date, timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from chores.models import ChildProfile, ChoreRevision, Occurrence
from chores.services import (
    complete_occurrence,
    create_chore,
    generate_occurrences,
    mark_overdue_occurrences,
    revise_chore,
)

pytestmark = pytest.mark.django_db


def chore_values(**overrides):
    values = {
        "name": "Dishes",
        "description": "Load and unload",
        "estimated_minutes": 20,
        "recurrence": ChoreRevision.Recurrence.DAILY,
        "due_weekday": None,
        "child_eligible": False,
        "is_active": True,
    }
    values.update(overrides)
    return values


def test_chore_changes_are_effective_next_week(organizer):
    today = date(2026, 9, 2)
    chore = create_chore(actor=organizer, values=chore_values(), today=today)
    original = chore.revisions.get()

    revised = revise_chore(
        chore=chore,
        actor=organizer,
        values=chore_values(name="Kitchen cleanup", estimated_minutes=30),
        today=today + timedelta(days=7),
    )

    assert original.effective_from == date(2026, 9, 7)
    assert revised.effective_from == date(2026, 9, 14)
    assert original.name == "Dishes"
    assert original.estimated_minutes == 20


def test_outsider_cannot_revise_chore(organizer, outsider):
    chore = create_chore(actor=organizer, values=chore_values())
    with pytest.raises(PermissionDenied):
        revise_chore(chore=chore, actor=outsider, values=chore_values())


def test_daily_and_weekly_generation_is_idempotent(organizer):
    monday = date(2026, 9, 7)
    create_chore(
        actor=organizer,
        values=chore_values(),
        today=monday - timedelta(days=1),
    )
    create_chore(
        actor=organizer,
        values=chore_values(
            name="Bins",
            recurrence=ChoreRevision.Recurrence.WEEKLY,
            due_weekday=4,
        ),
        today=monday - timedelta(days=1),
    )

    first = generate_occurrences(
        household=organizer.membership.household, week_start=monday
    )
    second = generate_occurrences(
        household=organizer.membership.household, week_start=monday
    )

    assert len(first) == 8
    assert len(second) == 8
    assert Occurrence.objects.count() == 8
    assert Occurrence.objects.filter(due_date=monday + timedelta(days=4)).count() == 2


def test_generation_requires_monday(organizer):
    with pytest.raises(ValidationError):
        generate_occurrences(
            household=organizer.membership.household,
            week_start=date(2026, 9, 8),
        )


def test_revision_does_not_change_existing_occurrence(organizer):
    monday = date(2026, 9, 7)
    chore = create_chore(
        actor=organizer,
        values=chore_values(),
        today=monday - timedelta(days=1),
    )
    occurrence = generate_occurrences(
        household=organizer.membership.household, week_start=monday
    )[0]
    revise_chore(
        chore=chore,
        actor=organizer,
        values=chore_values(estimated_minutes=45),
        today=monday,
    )
    occurrence.refresh_from_db()

    assert occurrence.estimated_minutes == 20
    assert occurrence.revision.estimated_minutes == 20


def test_unfinished_occurrences_become_overdue(organizer):
    revision = create_chore(
        actor=organizer,
        values=chore_values(),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence.objects.create(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
    )

    assert mark_overdue_occurrences(as_of=date(2026, 9, 8)) == 1
    occurrence.refresh_from_db()
    assert occurrence.status == Occurrence.Status.OVERDUE


def test_adult_completes_own_occurrence(member):
    revision = create_chore(
        actor=member,
        values=chore_values(),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence.objects.create(
        household=member.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        assigned_user=member,
    )

    complete_occurrence(occurrence=occurrence, actor=member, note="All done")

    assert occurrence.status == Occurrence.Status.COMPLETED
    assert occurrence.completed_by == member
    assert occurrence.completion_note == "All done"


def test_adult_cannot_complete_someone_elses_occurrence(organizer, member):
    revision = create_chore(
        actor=organizer,
        values=chore_values(),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence.objects.create(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        assigned_user=organizer,
    )

    with pytest.raises(PermissionDenied):
        complete_occurrence(occurrence=occurrence, actor=member)


def test_organizer_completes_child_occurrence(organizer):
    child = ChildProfile.objects.create(
        household=organizer.membership.household, name="Ari"
    )
    revision = create_chore(
        actor=organizer,
        values=chore_values(child_eligible=True),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence.objects.create(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        assigned_child=child,
    )

    complete_occurrence(occurrence=occurrence, actor=organizer)
    assert occurrence.status == Occurrence.Status.COMPLETED


def test_inactive_chore_does_not_generate_occurrences(organizer):
    monday = date(2026, 9, 7)
    create_chore(
        actor=organizer,
        values=chore_values(is_active=False),
        today=monday - timedelta(days=1),
    )
    assert (
        generate_occurrences(
            household=organizer.membership.household, week_start=monday
        )
        == []
    )


def test_generated_week_pushes_later_edit_to_following_week(organizer):
    monday = date(2026, 9, 7)
    chore = create_chore(
        actor=organizer,
        values=chore_values(),
        today=monday - timedelta(days=1),
    )
    generate_occurrences(household=organizer.membership.household, week_start=monday)

    revision = revise_chore(
        chore=chore,
        actor=organizer,
        values=chore_values(name="Later dishes"),
        today=monday - timedelta(days=1),
    )
    assert revision.effective_from == monday + timedelta(days=7)


def test_generation_uses_revision_effective_for_each_week(organizer):
    first_monday = date(2026, 9, 7)
    chore = create_chore(
        actor=organizer,
        values=chore_values(estimated_minutes=10),
        today=first_monday - timedelta(days=1),
    )
    revise_chore(
        chore=chore,
        actor=organizer,
        values=chore_values(estimated_minutes=30),
        today=first_monday,
    )

    first = generate_occurrences(
        household=organizer.membership.household, week_start=first_monday
    )
    second = generate_occurrences(
        household=organizer.membership.household,
        week_start=first_monday + timedelta(days=7),
    )
    assert {item.estimated_minutes for item in first} == {10}
    assert {item.estimated_minutes for item in second} == {30}


def test_overdue_job_ignores_today_and_completed_occurrences(organizer):
    revision = create_chore(
        actor=organizer,
        values=chore_values(),
        today=date(2026, 8, 30),
    ).revisions.get()
    today_item = Occurrence.objects.create(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 8),
        estimated_minutes=20,
    )
    completed = Occurrence.objects.create(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        status=Occurrence.Status.COMPLETED,
    )

    assert mark_overdue_occurrences(as_of=date(2026, 9, 8)) == 0
    today_item.refresh_from_db()
    completed.refresh_from_db()
    assert today_item.status == Occurrence.Status.PENDING
    assert completed.status == Occurrence.Status.COMPLETED


def test_completion_is_idempotent(member):
    revision = create_chore(
        actor=member,
        values=chore_values(),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence.objects.create(
        household=member.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        assigned_user=member,
    )
    complete_occurrence(occurrence=occurrence, actor=member, note="First")
    completed_at = occurrence.completed_at
    complete_occurrence(occurrence=occurrence, actor=member, note="Second")

    assert occurrence.completed_at == completed_at
    assert occurrence.completion_note == "First"


def test_member_cannot_complete_child_occurrence(organizer, member):
    child = ChildProfile.objects.create(
        household=organizer.membership.household, name="Ari"
    )
    revision = create_chore(
        actor=organizer,
        values=chore_values(child_eligible=True),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence.objects.create(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        assigned_child=child,
    )
    with pytest.raises(PermissionDenied):
        complete_occurrence(occurrence=occurrence, actor=member)


def test_completion_rejects_other_household_and_long_note(organizer, outsider):
    revision = create_chore(
        actor=organizer,
        values=chore_values(),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence.objects.create(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        assigned_user=organizer,
    )
    with pytest.raises(PermissionDenied):
        complete_occurrence(occurrence=occurrence, actor=outsider)
    with pytest.raises(ValidationError):
        complete_occurrence(occurrence=occurrence, actor=organizer, note="x" * 281)


def test_occurrence_validation_enforces_household_and_child_eligibility(
    organizer, outsider
):
    revision = create_chore(
        actor=organizer,
        values=chore_values(child_eligible=False),
        today=date(2026, 8, 30),
    ).revisions.get()
    foreign_child = ChildProfile.objects.create(
        household=outsider.membership.household, name="Bo"
    )
    occurrence = Occurrence(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        assigned_child=foreign_child,
    )
    with pytest.raises(ValidationError):
        occurrence.full_clean()


def test_chore_revision_model_rejects_invalid_recurrence_combinations(organizer):
    chore = create_chore(
        actor=organizer,
        values=chore_values(),
        today=date(2026, 8, 30),
    )
    daily_with_weekday = ChoreRevision(
        chore=chore,
        effective_from=date(2026, 9, 14),
        **chore_values(due_weekday=2),
    )
    weekly_without_weekday = ChoreRevision(
        chore=chore,
        effective_from=date(2026, 9, 14),
        **chore_values(
            recurrence=ChoreRevision.Recurrence.WEEKLY,
            due_weekday=None,
        ),
    )
    with pytest.raises(ValidationError):
        daily_with_weekday.clean()
    with pytest.raises(ValidationError):
        weekly_without_weekday.clean()


def test_occurrence_rejects_mismatched_chore_revision(organizer, outsider):
    revision = create_chore(
        actor=organizer,
        values=chore_values(),
        today=date(2026, 8, 30),
    ).revisions.get()
    other_revision = create_chore(
        actor=outsider,
        values=chore_values(name="Other"),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=other_revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
    )
    with pytest.raises(ValidationError):
        occurrence.full_clean()


def test_occurrence_rejects_foreign_adult_assignee(organizer, outsider):
    revision = create_chore(
        actor=organizer,
        values=chore_values(),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        assigned_user=outsider,
    )
    with pytest.raises(ValidationError):
        occurrence.full_clean()


def test_occurrence_rejects_child_for_adult_only_chore(organizer):
    child = ChildProfile.objects.create(
        household=organizer.membership.household, name="Ari"
    )
    revision = create_chore(
        actor=organizer,
        values=chore_values(child_eligible=False),
        today=date(2026, 8, 30),
    ).revisions.get()
    occurrence = Occurrence(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=20,
        assigned_child=child,
    )
    with pytest.raises(ValidationError):
        occurrence.full_clean()
