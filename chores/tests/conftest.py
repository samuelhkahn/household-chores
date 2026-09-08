import pytest

from chores.models import Household, Membership, User


@pytest.fixture
def organizer(db):
    user = User.objects.create_user("organizer@example.com", "test-password-123")
    household = Household.objects.create(name="Oak House")
    Membership.objects.create(
        user=user, household=household, role=Membership.Role.ORGANIZER
    )
    return user


@pytest.fixture
def member(db, organizer):
    user = User.objects.create_user("member@example.com", "test-password-123")
    Membership.objects.create(user=user, household=organizer.membership.household)
    return user


@pytest.fixture
def outsider(db):
    user = User.objects.create_user("outsider@example.com", "test-password-123")
    household = Household.objects.create(name="Other House")
    Membership.objects.create(
        user=user, household=household, role=Membership.Role.ORGANIZER
    )
    return user
