from django.contrib import admin
from .models import *


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

@admin.register(Events)
class EventsAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']

@admin.register(AwardType)
class AwardTypeAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']

@admin.register(Award)
class AwardAdmin(admin.ModelAdmin):
    list_display = ['id', 'award_type', 'person', 'given_at', 'streak_at_award', 'given_by']
    list_filter = ['award_type', 'given_at']
    search_fields = ['person__first_name', 'person__last_name', 'award_type__name']
    ordering = ['-given_at']


@admin.register(MemberStreak)
class MemberStreakAdmin(admin.ModelAdmin):
    list_display = ['id', 'person', 'current_streak', 'longest_streak']
    list_filter = ['current_streak', 'longest_streak']
    search_fields = ['person__first_name', 'person__last_name']
    ordering = ['-current_streak']

@admin.register(RosterFeedback)
class RosterFeedbackAdmin(admin.ModelAdmin):
    list_display = ['id', 'roster', 'person', 'created_at']
    list_filter = ['created_at']
    search_fields = ['roster__event__name', 'roster__date']
    ordering = ['-created_at']