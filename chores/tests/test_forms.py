import pytest

from chores.forms import (
    ChoreForm,
    CompletionForm,
    HouseholdForm,
    InvitationAcceptanceForm,
)
from chores.models import ChoreRevision

pytestmark = pytest.mark.django_db


def chore_data(**overrides):
    data = {
        "name": "Sweep",
        "description": "",
        "estimated_minutes": 10,
        "recurrence": ChoreRevision.Recurrence.WEEKLY,
        "due_weekday": "1",
        "child_eligible": False,
        "is_active": True,
    }
    data.update(overrides)
    return data


def test_household_form_accepts_real_timezone():
    form = HouseholdForm({"name": "Home", "timezone": "America/Los_Angeles"})
    assert form.is_valid()


def test_daily_chore_discards_weekday():
    form = ChoreForm(
        chore_data(recurrence=ChoreRevision.Recurrence.DAILY, due_weekday="4")
    )
    assert form.is_valid()
    assert form.cleaned_data["due_weekday"] is None


def test_weekly_chore_requires_weekday():
    form = ChoreForm(chore_data(due_weekday=""))
    assert not form.is_valid()
    assert "due_weekday" in form.errors


def test_invitation_passwords_must_match():
    form = InvitationAcceptanceForm(
        {
            "first_name": "Ari",
            "last_name": "",
            "password": "safe-password-123",
            "password_confirmation": "different-password-123",
        }
    )
    assert not form.is_valid()
    assert "password_confirmation" in form.errors


def test_completion_note_has_hard_length_limit():
    form = CompletionForm({"note": "x" * 281})
    assert not form.is_valid()
    assert "note" in form.errors
