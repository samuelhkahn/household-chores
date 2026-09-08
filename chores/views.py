from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    AssignmentForm,
    CapacityForm,
    ChildProfileForm,
    ChoreForm,
    CompletionForm,
    HouseholdForm,
    InvitationAcceptanceForm,
    InvitationForm,
    ReassignmentDecisionForm,
    ReassignmentRequestForm,
)
from .models import (
    ChildProfile,
    Chore,
    FairnessSummary,
    Membership,
    Occurrence,
    ReassignmentRequest,
    User,
)
from .services import (
    accept_invitation,
    complete_occurrence,
    create_child,
    create_chore,
    create_household,
    create_invitation,
    decide_reassignment,
    invitation_for_token,
    membership_for,
    next_week_start,
    override_assignment,
    request_reassignment,
    require_organizer,
    revise_chore,
    set_capacity,
    week_start_for,
)


def health(request):
    return JsonResponse({"status": "ok"})


def readiness(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})


@login_required
def home(request):
    try:
        membership = membership_for(request.user)
    except PermissionDenied:
        return render(request, "chores/onboarding.html")
    household = membership.household
    chores = list(
        Chore.objects.filter(household=household).prefetch_related("revisions")
    )
    for chore in chores:
        chore.latest_revision = chore.revisions.order_by("-effective_from").first()
    today = timezone.localdate()
    current_week = week_start_for(today)
    occurrences = Occurrence.objects.filter(
        household=household,
        due_date__range=(
            current_week - timedelta(days=7),
            current_week + timedelta(days=6),
        ),
    ).select_related("revision", "assigned_user", "assigned_child")
    my_occurrences = occurrences.filter(
        assigned_user=request.user,
        due_date__range=(current_week, current_week + timedelta(days=6)),
    )
    fairness = FairnessSummary.objects.filter(
        household=household, week_start=current_week
    ).select_related("user", "child")
    pending_requests = ReassignmentRequest.objects.filter(
        occurrence__household=household,
        status=ReassignmentRequest.Status.PENDING,
    ).select_related("occurrence__revision", "requested_by")
    return render(
        request,
        "chores/home.html",
        {
            "membership": membership,
            "household": household,
            "chores": chores,
            "occurrences": occurrences,
            "my_occurrences": my_occurrences,
            "fairness": fairness,
            "pending_requests": pending_requests,
            "current_week": current_week,
            "next_week": next_week_start(today),
        },
    )


@login_required
def household_create(request):
    if Membership.objects.filter(user=request.user).exists():
        raise PermissionDenied("You already belong to a household.")
    form = HouseholdForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        create_household(
            organizer=request.user,
            name=form.cleaned_data["name"],
            timezone_name=form.cleaned_data["timezone"],
        )
        messages.success(request, "Household created.")
        return redirect("chores:home")
    return render(request, "chores/form.html", {"form": form, "title": "Household"})


@login_required
def child_create(request):
    require_organizer(request.user)
    form = ChildProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_child(organizer=request.user, name=form.cleaned_data["name"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Child profile created.")
            return redirect("chores:home")
    return render(request, "chores/form.html", {"form": form, "title": "Add child"})


@login_required
def invitation_create(request):
    require_organizer(request.user)
    form = InvitationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            invitation, token = create_invitation(
                organizer=request.user, **form.cleaned_data
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            invitation_url = request.build_absolute_uri(f"/invitations/{token}/accept/")
            return render(
                request,
                "chores/invitation_created.html",
                {
                    "invitation": invitation,
                    "invitation_url": invitation_url,
                },
            )
    return render(request, "chores/form.html", {"form": form, "title": "Invite adult"})


def invitation_accept(request, token):
    try:
        invitation = invitation_for_token(token)
    except ValidationError as exc:
        return render(
            request,
            "chores/invitation_invalid.html",
            {
                "error": exc.messages[0],
            },
            status=400,
        )
    form = InvitationAcceptanceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = accept_invitation(
                token=token,
                password=form.cleaned_data["password"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            login(request, user)
            messages.success(request, "Invitation accepted.")
            return redirect("chores:home")
    return render(
        request,
        "chores/invitation_accept.html",
        {
            "form": form,
            "invitation": invitation,
        },
    )


def _chore_values(form):
    return {field: form.cleaned_data[field] for field in form.Meta.fields}


@login_required
def chore_create(request):
    membership_for(request.user)
    form = ChoreForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        create_chore(actor=request.user, values=_chore_values(form))
        messages.success(request, "Chore scheduled for next week.")
        return redirect("chores:home")
    return render(request, "chores/form.html", {"form": form, "title": "Add chore"})


@login_required
def chore_edit(request, chore_id):
    membership = membership_for(request.user)
    chore = get_object_or_404(Chore, id=chore_id, household=membership.household)
    latest = chore.revisions.order_by("-effective_from").first()
    form = ChoreForm(request.POST or None, instance=latest)
    if request.method == "POST" and form.is_valid():
        revise_chore(chore=chore, actor=request.user, values=_chore_values(form))
        messages.success(request, "Changes scheduled for next week.")
        return redirect("chores:home")
    return render(request, "chores/form.html", {"form": form, "title": "Edit chore"})


@login_required
def occurrence_complete(request, occurrence_id):
    membership = membership_for(request.user)
    occurrence = get_object_or_404(
        Occurrence, id=occurrence_id, household=membership.household
    )
    form = CompletionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        complete_occurrence(
            occurrence=occurrence,
            actor=request.user,
            note=form.cleaned_data["note"],
        )
        messages.success(request, "Chore marked complete.")
        return redirect("chores:home")
    return render(
        request,
        "chores/form.html",
        {
            "form": form,
            "title": f"Complete {occurrence.revision.name}",
        },
    )


def _selected_assignee(value, household):
    kind, raw_id = value.split(":", 1)
    if kind == "user":
        user = get_object_or_404(
            User,
            id=raw_id,
            membership__household=household,
            membership__is_active=True,
            is_active=True,
        )
        return {"user": user, "child": None}
    child = get_object_or_404(
        ChildProfile, id=raw_id, household=household, is_active=True
    )
    return {"user": None, "child": child}


@login_required
def capacity_update(request):
    membership = membership_for(request.user)
    week_start = next_week_start()
    form = CapacityForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        set_capacity(
            actor=request.user,
            week_start=week_start,
            level=form.cleaned_data["level"],
        )
        messages.success(request, f"Capacity saved for the week of {week_start}.")
        return redirect("chores:home")
    return render(
        request,
        "chores/form.html",
        {
            "form": form,
            "title": f"Your capacity for {week_start}",
            "membership": membership,
        },
    )


@login_required
def reassignment_request_create(request, occurrence_id):
    membership = membership_for(request.user)
    occurrence = get_object_or_404(
        Occurrence, id=occurrence_id, household=membership.household
    )
    form = ReassignmentRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            request_reassignment(
                occurrence=occurrence,
                actor=request.user,
                reason=form.cleaned_data["reason"],
            )
        except (PermissionDenied, ValidationError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Reassignment requested.")
            return redirect("chores:home")
    return render(
        request,
        "chores/form.html",
        {"form": form, "title": f"Reassign {occurrence.revision.name}"},
    )


@login_required
def reassignment_decide(request, request_id):
    membership = require_organizer(request.user)
    reassignment = get_object_or_404(
        ReassignmentRequest,
        id=request_id,
        occurrence__household=membership.household,
        status=ReassignmentRequest.Status.PENDING,
    )
    form = ReassignmentDecisionForm(
        request.POST or None,
        household=membership.household,
        occurrence=reassignment.occurrence,
    )
    if request.method == "POST" and form.is_valid():
        replacement = (
            _selected_assignee(form.cleaned_data["assignee"], membership.household)
            if form.cleaned_data["decision"] == "approve"
            else {"user": None, "child": None}
        )
        try:
            decide_reassignment(
                request=reassignment,
                actor=request.user,
                approve=form.cleaned_data["decision"] == "approve",
                reason=form.cleaned_data["reason"],
                **replacement,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Reassignment decision recorded.")
            return redirect("chores:home")
    return render(
        request,
        "chores/form.html",
        {"form": form, "title": f"Review {reassignment.occurrence.revision.name}"},
    )


@login_required
def occurrence_override(request, occurrence_id):
    membership = require_organizer(request.user)
    occurrence = get_object_or_404(
        Occurrence, id=occurrence_id, household=membership.household
    )
    form = AssignmentForm(
        request.POST or None,
        household=membership.household,
        occurrence=occurrence,
    )
    if request.method == "POST" and form.is_valid():
        replacement = _selected_assignee(
            form.cleaned_data["assignee"], membership.household
        )
        try:
            override_assignment(
                occurrence=occurrence,
                actor=request.user,
                reason=form.cleaned_data["reason"],
                **replacement,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Assignment overridden.")
            return redirect("chores:home")
    return render(
        request,
        "chores/form.html",
        {"form": form, "title": f"Override {occurrence.revision.name}"},
    )
