import pytest
from django.urls import reverse

from chores.models import ChoreRevision, Occurrence
from chores.services import create_chore

pytestmark = pytest.mark.django_db


def values():
    return {
        "name": "Vacuum",
        "description": "",
        "estimated_minutes": 30,
        "recurrence": ChoreRevision.Recurrence.WEEKLY,
        "due_weekday": 5,
        "child_eligible": False,
        "is_active": True,
    }


def test_member_cannot_open_organizer_child_form(client, member):
    client.force_login(member)
    response = client.get(reverse("chores:child-create"))
    assert response.status_code == 403


def test_member_cannot_open_invitation_form(client, member):
    client.force_login(member)
    response = client.get(reverse("chores:invitation-create"))
    assert response.status_code == 403


def test_outsider_cannot_open_chore_edit(client, organizer, outsider):
    chore = create_chore(actor=organizer, values=values())
    client.force_login(outsider)
    response = client.get(reverse("chores:chore-edit", args=[chore.id]))
    assert response.status_code == 404


def test_anonymous_user_is_redirected_to_login(client):
    response = client.get(reverse("chores:home"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_outsider_cannot_open_occurrence_completion(client, organizer, outsider):
    chore = create_chore(actor=organizer, values=values())
    revision = chore.revisions.get()
    occurrence = Occurrence.objects.create(
        household=organizer.membership.household,
        chore=chore,
        revision=revision,
        due_date=revision.effective_from,
        estimated_minutes=30,
        assigned_user=organizer,
    )
    client.force_login(outsider)
    response = client.get(reverse("chores:occurrence-complete", args=[occurrence.id]))
    assert response.status_code == 404
