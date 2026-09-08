from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from chores.models import ChoreRevision, Occurrence
from chores.services import create_chore

pytestmark = pytest.mark.django_db


def values():
    return {
        "name": "Bins",
        "description": "",
        "estimated_minutes": 10,
        "recurrence": ChoreRevision.Recurrence.WEEKLY,
        "due_weekday": 0,
        "child_eligible": False,
        "is_active": True,
    }


def test_generate_occurrences_command(organizer):
    monday = date(2026, 9, 7)
    create_chore(actor=organizer, values=values(), today=monday - timedelta(days=1))
    output = StringIO()

    call_command(
        "generate_occurrences",
        organizer.membership.household_id,
        monday,
        stdout=output,
    )

    assert Occurrence.objects.count() == 1
    assert "Ensured 1 occurrences" in output.getvalue()


def test_generate_occurrences_command_reports_bad_input(organizer):
    with pytest.raises(CommandError, match="does not exist"):
        call_command("generate_occurrences", 999_999, date(2026, 9, 7))
    with pytest.raises(CommandError, match="Monday"):
        call_command(
            "generate_occurrences",
            organizer.membership.household_id,
            date(2026, 9, 8),
        )


def test_mark_overdue_command(organizer):
    revision = create_chore(
        actor=organizer, values=values(), today=date(2026, 8, 30)
    ).revisions.get()
    occurrence = Occurrence.objects.create(
        household=organizer.membership.household,
        chore=revision.chore,
        revision=revision,
        due_date=date(2026, 9, 7),
        estimated_minutes=10,
    )
    output = StringIO()

    call_command("mark_overdue", as_of=date(2026, 9, 8), stdout=output)

    occurrence.refresh_from_db()
    assert occurrence.status == Occurrence.Status.OVERDUE
    assert "Marked 1 occurrences" in output.getvalue()
