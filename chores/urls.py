from django.urls import path

from . import views

app_name = "chores"

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("ready/", views.readiness, name="readiness"),
    path("households/new/", views.household_create, name="household-create"),
    path("children/new/", views.child_create, name="child-create"),
    path("invitations/new/", views.invitation_create, name="invitation-create"),
    path(
        "invitations/<str:token>/accept/",
        views.invitation_accept,
        name="invitation-accept",
    ),
    path("chores/new/", views.chore_create, name="chore-create"),
    path("chores/<int:chore_id>/edit/", views.chore_edit, name="chore-edit"),
    path("capacity/", views.capacity_update, name="capacity-update"),
    path(
        "occurrences/<int:occurrence_id>/complete/",
        views.occurrence_complete,
        name="occurrence-complete",
    ),
    path(
        "occurrences/<int:occurrence_id>/reassign/",
        views.reassignment_request_create,
        name="reassignment-request",
    ),
    path(
        "occurrences/<int:occurrence_id>/override/",
        views.occurrence_override,
        name="occurrence-override",
    ),
    path(
        "reassignments/<int:request_id>/decide/",
        views.reassignment_decide,
        name="reassignment-decide",
    ),
]
