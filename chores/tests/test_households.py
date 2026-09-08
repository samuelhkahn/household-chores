from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.utils import timezone

from chores.models import ChildProfile, Household, Invitation, Membership, User
from chores.services import (
    accept_invitation,
    create_child,
    create_household,
    create_invitation,
    invitation_for_token,
    membership_for,
)

pytestmark = pytest.mark.django_db


def test_email_is_the_login_identifier():
    assert User.USERNAME_FIELD == "email"
    assert not hasattr(User(), "username")


def test_user_can_belong_to_only_one_household(organizer):
    other = Household.objects.create(name="Other")
    with pytest.raises(IntegrityError):
        Membership.objects.create(user=organizer, household=other)


def test_new_household_creator_is_organizer(db):
    user = User.objects.create_user("new@example.com", "password")
    household = create_household(organizer=user, name="New Home", timezone_name="UTC")

    assert user.membership.household == household
    assert user.membership.is_organizer


def test_only_organizer_can_create_child(member):
    with pytest.raises(PermissionDenied):
        create_child(organizer=member, name="Sam")
    assert not ChildProfile.objects.exists()


def test_invitation_is_hashed_single_use_and_creates_membership(organizer):
    invitation, token = create_invitation(
        organizer=organizer,
        email="invited@example.com",
        role=Membership.Role.MEMBER,
    )

    assert invitation.token_digest != token
    user = accept_invitation(
        token=token, password="strong-pass-123", first_name="Invited"
    )
    assert user.membership.household == organizer.membership.household
    assert user.check_password("strong-pass-123")

    with pytest.raises(ValidationError):
        accept_invitation(token=token, password="another-pass-123")


def test_expired_invitation_cannot_be_accepted(organizer):
    invitation, token = create_invitation(
        organizer=organizer,
        email="late@example.com",
        role=Membership.Role.MEMBER,
    )
    invitation.expires_at = timezone.now() - timedelta(seconds=1)
    invitation.save(update_fields=["expires_at"])

    with pytest.raises(ValidationError):
        accept_invitation(token=token, password="strong-pass-123")


def test_reinviting_replaces_old_pending_token(organizer):
    old, _ = create_invitation(
        organizer=organizer,
        email="repeat@example.com",
        role=Membership.Role.MEMBER,
    )
    new, _ = create_invitation(
        organizer=organizer,
        email="repeat@example.com",
        role=Membership.Role.MEMBER,
    )

    assert not Invitation.objects.filter(pk=old.pk).exists()
    assert Invitation.objects.filter(pk=new.pk).exists()


def test_user_requires_email(db):
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user("", "password")


def test_superuser_has_required_flags(db):
    user = User.objects.create_superuser("admin@example.com", "password")
    assert user.is_staff
    assert user.is_superuser


def test_inactive_membership_is_denied(member):
    member.membership.is_active = False
    member.membership.save(update_fields=["is_active"])
    with pytest.raises(PermissionDenied):
        membership_for(member)


def test_existing_member_cannot_create_another_household(organizer):
    with pytest.raises(ValidationError):
        create_household(organizer=organizer, name="Second", timezone_name="UTC")


def test_member_cannot_invite(member):
    with pytest.raises(PermissionDenied):
        create_invitation(
            organizer=member,
            email="person@example.com",
            role=Membership.Role.MEMBER,
        )


def test_invitation_rejects_invalid_role_and_existing_member(organizer, member):
    with pytest.raises(ValidationError):
        create_invitation(organizer=organizer, email="person@example.com", role="owner")
    with pytest.raises(ValidationError):
        create_invitation(
            organizer=organizer,
            email=member.email,
            role=Membership.Role.MEMBER,
        )


def test_invalid_token_is_rejected(organizer):
    with pytest.raises(ValidationError):
        invitation_for_token("not-a-token")
    with pytest.raises(ValidationError):
        accept_invitation(token="not-a-token", password="strong-pass-123")


def test_duplicate_child_name_is_rejected(organizer):
    create_child(organizer=organizer, name="Ari")
    with pytest.raises(ValidationError):
        create_child(organizer=organizer, name="Ari")


def test_expired_invitation_cannot_be_looked_up(organizer):
    invitation, token = create_invitation(
        organizer=organizer,
        email="expired@example.com",
        role=Membership.Role.MEMBER,
    )
    invitation.expires_at = timezone.now() - timedelta(seconds=1)
    invitation.save(update_fields=["expires_at"])
    with pytest.raises(ValidationError, match="expired"):
        invitation_for_token(token)


def test_existing_account_cannot_be_claimed_with_invitation(organizer):
    User.objects.create_user("existing@example.com", "original-password")
    _, token = create_invitation(
        organizer=organizer,
        email="existing@example.com",
        role=Membership.Role.MEMBER,
    )
    with pytest.raises(ValidationError, match="already exists"):
        accept_invitation(token=token, password="replacement-password")
