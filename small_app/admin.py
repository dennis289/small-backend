from django.contrib import admin
from .models import (
    User, Persons, Roles, Events, Rosters, Assignment,
    AwardType, Award, RosterFeedback,
)


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0
    autocomplete_fields = ['person', 'role']


@admin.register(Rosters)
class RostersAdmin(admin.ModelAdmin):
    list_display = ['id', 'event', 'date', 'created_at']
    list_filter = ['date', 'event']
    ordering = ['-date']
    inlines = [AssignmentInline]


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'person', 'role', 'roster']
    list_filter = ['role', 'roster__date']
    search_fields = ['person__first_name', 'person__last_name', 'role__name']
    ordering = ['-roster__date']


@admin.register(Persons)
class PersonsAdmin(admin.ModelAdmin):
    list_display = ['id', 'first_name', 'last_name', 'email', 'is_producer', 'is_assistant_producer', 'is_present', 'is_active']
    list_filter = ['is_producer', 'is_assistant_producer', 'is_present', 'is_active']
    search_fields = ['first_name', 'last_name', 'email']
    filter_horizontal = ['roles']


@admin.register(Roles)
class RolesAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'is_special_role', 'max_assignments']
    list_filter = ['is_special_role']
    search_fields = ['name']


admin.site.register(Events)
admin.site.register(User)
admin.site.register(AwardType)
admin.site.register(Award)
admin.site.register(RosterFeedback)
