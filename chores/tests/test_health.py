from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.urls import reverse


def test_health(client):
    response = client.get(reverse("chores:health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readiness_checks_database(client):
    response = client.get(reverse("chores:readiness"))

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.django_db
def test_readiness_reports_database_failure(client):
    with patch("chores.views.connection.cursor", side_effect=OperationalError):
        response = client.get(reverse("chores:readiness"))

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
