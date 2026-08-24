from .views import *
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


urlpatterns = [
    # Existing URLs
    path('signup/', signup, name='signup'),
    path('login/', login, name='login'),
    path('user/profile/', user_profile, name='user_profile'),
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # Public password reset: request a link, then redeem the token it carries.
    path('password-reset/', password_reset_request, name='password_reset_request'),
    path('password-reset/confirm/', password_reset_confirm, name='password_reset_confirm'),
    path('persons/', persons, name='persons'),
    path('persons/active/', active_members, name='active_members'),
    path('persons/streaks/', person_streaks, name='person_streaks'),
    path('persons/modify/<int:id>/', modify_person, name='modify_person'),
    path('persons/<int:pk>/', person_detail, name='person_detail'),
    path('persons/bulk-upload/', bulk_upload_persons, name='bulk_upload_persons'),
    path('roles/', roles, name='roles'),
    path('roles/modify/<int:id>/', modify_role, name='modify_role'),
    path('roles/reorder/', reorder_roles, name='reorder_roles'),
    path('roles/<int:pk>/', role_detail, name='role_detail'),
    path('events/', events, name='events'),
    path('events/modify/<int:id>/', modify_event, name='modify_event'),
    path('events/<int:pk>/', event_detail, name='event_detail'),
    path('rosters/', rosters, name='rosters'),
    path('rosters/save/', save_roster, name='save_roster'),
    path('rosters/statistics/', roster_statistics, name='roster_statistics'),
    # Read-only published roster — the only roster data a member can reach.
    path('rosters/dates/', roster_dates, name='roster_dates'),
    path('rosters/day/<str:date_str>/', roster_day, name='roster_day'),
    # Saved roster in generator-payload shape, so the generator page can reopen it.
    path('rosters/saved/<str:date_str>/', saved_roster, name='saved_roster'),
    # path('rosters/generate/',generate_structured_roster),  # Removed - conflicts with API endpoint
    path('assignments/', assignments, name='assignments'),
    path('assignments/<int:pk>/', assignment_detail, name='assignment_detail'),
    path('availability/status-choices/', get_status, name='status-choices'),
    path('generate-roster/', generate_and_download_roster, name='generate_roster'),
    # Awards
    path('award-types/', award_types, name='award_types'),
    path('award-types/<int:pk>/', award_type_detail, name='award_type_detail'),
    path('awards/', awards, name='awards'),
    path('awards/stats/', award_stats, name='award_stats'),
    path('awards/<int:pk>/', award_detail, name='award_detail'),
    path('persons/<int:pk>/awards/', person_awards, name='person_awards'),
    # Roster Feedback
    path('rosters/<int:roster_id>/persons/', roster_persons, name='roster_persons'),
    path('rosters/<int:roster_id>/feedback/', submit_feedback, name='submit_feedback'),
    path('rosters/<int:roster_id>/feedback/list/', roster_feedback, name='roster_feedback'),
    # Shareable feedback link
    path('feedback/summary/', feedback_summary, name='feedback_summary'),
    path('feedback/summary/<str:date_str>/', update_day_feedback, name='update_day_feedback'),
    # Tenant user management — a client admin managing their own client's logins
    path('users/', client_users, name='client_users'),
    path('users/<int:pk>/', client_user_detail, name='client_user_detail'),
    # Platform superadmin — client (tenant) management
    path('admin/clients/', admin_clients, name='admin_clients'),
    path('admin/clients/<int:pk>/', admin_client_detail, name='admin_client_detail'),
    path('admin/clients/<int:pk>/users/', admin_client_users, name='admin_client_users'),
    path('feedback/share/links/', create_feedback_share_link, name='create_feedback_share_link'),
    path('feedback/share/<str:token>/', feedback_share_get, name='feedback_share_get'),
    path('feedback/share/<str:token>/submit/', feedback_share_submit, name='feedback_share_submit'),
] 