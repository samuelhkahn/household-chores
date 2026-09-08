from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AssignmentAudit,
    ChildProfile,
    Chore,
    ChoreRevision,
    EmailDelivery,
    FairnessSummary,
    Household,
    Invitation,
    Membership,
    Occurrence,
    ReassignmentRequest,
    ScheduledJob,
    User,
    WeeklyCapacity,
)


@admin.register(User)
class EmailUserAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal information", {"fields": ("first_name", "last_name")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                ),
            },
        ),
    )


admin.site.register(Household)
admin.site.register(Membership)
admin.site.register(ChildProfile)
admin.site.register(Invitation)
admin.site.register(Chore)
admin.site.register(ChoreRevision)
admin.site.register(Occurrence)
admin.site.register(WeeklyCapacity)
admin.site.register(FairnessSummary)
admin.site.register(ReassignmentRequest)
admin.site.register(AssignmentAudit)
admin.site.register(EmailDelivery)
admin.site.register(ScheduledJob)
