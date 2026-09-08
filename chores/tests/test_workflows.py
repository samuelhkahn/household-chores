from datetime import date

import pytest
from django.urls import reverse

from chores.models import (
    ChildProfile,
    Chore,
    ChoreRevision,
    Invitation,
    Membership,
    Occurrence,
    User,
)
from chores.services import create_chore, create_invitation

pytestmark = pytest.mark.django_db


def values():
    return {
        "name": "Laundry",
        "description": "Fold everything",
        "estimated_minutes": 25,
        "recurrence": ChoreRevision.Recurrence.WEEKLY,
        "due_weekday": 2,
        "child_eligible": False,
        "is_active": True,
    }


def test_organizer_can_create_child_from_form(client, organizer):
    client.force_login(organizer)
    response = client.post(reverse("chores:child-create"), {"name": "Ari"})

    assert response.status_code == 302
    assert ChildProfile.objects.filter(
        household=organizer.membership.household, name="Ari"
    ).exists()


def test_member_can_create_chore_from_form(client, member):
    client.force_login(member)
    response = client.post(reverse("chores:chore-create"), values())

    assert response.status_code == 302
    chore = Chore.objects.get(household=member.membership.household)
    assert chore.revisions.get().name == "Laundry"


def test_invited_adult_can_accept_and_sign_in(client, organizer):
    _, token = create_invitation(
        organizer=organizer,
        email="joiner@example.com",
        role=Membership.Role.MEMBER,
    )
    response = client.post(
        reverse("chores:invitation-accept", args=[token]),
        {
            "first_name": "Jo",
            "last_name": "Iner",
            "password": "safe-password-8675309",
            "password_confirmation": "safe-password-8675309",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("chores:home")
    assert client.get(reverse("chores:home")).status_code == 200


def test_assignee_can_complete_from_form(client, member):
    chore = create_chore(actor=member, values=values(), today=date(2026, 9, 6))
    revision = chore.revisions.get()
    occurrence = Occurrence.objects.create(
        household=member.membership.household,
        chore=chore,
        revision=revision,
        due_date=date(2026, 9, 9),
        estimated_minutes=25,
        assigned_user=member,
    )
    client.force_login(member)

    response = client.post(
        reverse("chores:occurrence-complete", args=[occurrence.id]),
        {"note": "Done before dinner"},
    )

    assert response.status_code == 302
    occurrence.refresh_from_db()
    assert occurrence.status == Occurrence.Status.COMPLETED


def test_new_user_can_create_household_from_onboarding(client):
    user = User.objects.create_user("new@example.com", "safe-password-123")
    client.force_login(user)
    assert client.get(reverse("chores:home")).status_code == 200

    response = client.post(
        reverse("chores:household-create"),
        {"name": "New Home", "timezone": "America/Los_Angeles"},
    )

    assert response.status_code == 302
    assert user.membership.household.name == "New Home"


def test_existing_member_cannot_open_household_creation(client, member):
    client.force_login(member)
    assert client.get(reverse("chores:household-create")).status_code == 403


def test_organizer_can_create_invitation_from_form(client, organizer):
    client.force_login(organizer)
    response = client.post(
        reverse("chores:invitation-create"),
        {"email": "new-member@example.com", "role": Membership.Role.MEMBER},
    )

    assert response.status_code == 200
    invitation = Invitation.objects.get(email="new-member@example.com")
    assert invitation.household == organizer.membership.household
    assert "accept" in response.content.decode()


def test_invalid_invitation_page_is_safe(client):
    response = client.get(reverse("chores:invitation-accept", args=["invalid-token"]))
    assert response.status_code == 400
    assert b"Invitation unavailable" in response.content


def test_invalid_chore_form_does_not_create_chore(client, member):
    client.force_login(member)
    invalid = values()
    invalid["due_weekday"] = ""
    response = client.post(reverse("chores:chore-create"), invalid)

    assert response.status_code == 200
    assert not Chore.objects.exists()


def test_member_can_edit_chore_for_next_week(client, member):
    chore = create_chore(actor=member, values=values(), today=date(2026, 9, 1))
    client.force_login(member)
    changed = values()
    changed["name"] = "Laundry and linens"

    response = client.post(reverse("chores:chore-edit", args=[chore.id]), changed)

    assert response.status_code == 302
    assert chore.revisions.order_by("-created_at").first().name == "Laundry and linens"


def test_duplicate_child_form_shows_validation_error(client, organizer):
    ChildProfile.objects.create(household=organizer.membership.household, name="Ari")
    client.force_login(organizer)
    response = client.post(reverse("chores:child-create"), {"name": "Ari"})

    assert response.status_code == 200
    assert b"already exists" in response.content
