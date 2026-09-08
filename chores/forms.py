from zoneinfo import ZoneInfo, available_timezones

from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import ChoreRevision, Membership, WeeklyCapacity

WEEKDAYS = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


class HouseholdForm(forms.Form):
    name = forms.CharField(max_length=120)
    timezone = forms.ChoiceField(
        choices=[(value, value) for value in sorted(available_timezones())],
        initial="UTC",
    )

    def clean_timezone(self):
        value = self.cleaned_data["timezone"]
        ZoneInfo(value)
        return value


class InvitationForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=Membership.Role)


class InvitationAcceptanceForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirmation = forms.CharField(widget=forms.PasswordInput)

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        if password and password != cleaned_data.get("password_confirmation"):
            self.add_error("password_confirmation", "Passwords do not match.")
        if password:
            validate_password(password)
        return cleaned_data


class ChildProfileForm(forms.Form):
    name = forms.CharField(max_length=120)


class ChoreForm(forms.ModelForm):
    due_weekday = forms.TypedChoiceField(
        choices=[("", "Every day"), *WEEKDAYS],
        coerce=lambda value: None if value == "" else int(value),
        empty_value=None,
        required=False,
    )

    class Meta:
        model = ChoreRevision
        fields = [
            "name",
            "description",
            "estimated_minutes",
            "recurrence",
            "due_weekday",
            "child_eligible",
            "is_active",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned_data = super().clean()
        recurrence = cleaned_data.get("recurrence")
        due_weekday = cleaned_data.get("due_weekday")
        if recurrence == ChoreRevision.Recurrence.DAILY:
            cleaned_data["due_weekday"] = None
        elif recurrence == ChoreRevision.Recurrence.WEEKLY and due_weekday is None:
            self.add_error("due_weekday", "Choose a weekday for a weekly chore.")
        return cleaned_data


class CompletionForm(forms.Form):
    note = forms.CharField(
        max_length=280, required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


class CapacityForm(forms.Form):
    level = forms.ChoiceField(choices=WeeklyCapacity.Level)


class ReassignmentRequestForm(forms.Form):
    reason = forms.CharField(
        max_length=280, required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


class AssignmentForm(forms.Form):
    assignee = forms.ChoiceField()
    reason = forms.CharField(
        max_length=280, required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, household, occurrence, **kwargs):
        super().__init__(*args, **kwargs)
        adults = [
            (f"user:{membership.user_id}", membership.user.get_short_name())
            for membership in household.memberships.select_related("user")
            .filter(is_active=True, user__is_active=True)
            .order_by("user_id")
        ]
        children = []
        if occurrence.revision.child_eligible:
            children = [
                (f"child:{child.id}", child.name)
                for child in household.children.filter(is_active=True).order_by("id")
            ]
        self.fields["assignee"].choices = adults + children


class ReassignmentDecisionForm(AssignmentForm):
    decision = forms.ChoiceField(choices=[("approve", "Approve"), ("reject", "Reject")])

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "reject":
            cleaned["assignee"] = ""
            self.errors.pop("assignee", None)
        elif not cleaned.get("assignee"):
            self.add_error("assignee", "Choose a replacement when approving.")
        return cleaned
