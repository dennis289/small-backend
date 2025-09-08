from django.urls import path
from .api_views import *

# API URLs for Flutter app
api_urlpatterns = [
    # Authentication
    path('auth/login/', api_login, name='api_login'),
    path('auth/signup/', api_signup, name='api_signup'),
    
    # People endpoints
    path('people/', api_people, name='api_people'),
    path('people/<int:pk>/', api_person_detail, name='api_person_detail'),
    # Alternative endpoint for frontend compatibility
    path('persons/', api_people, name='api_persons'),
    
    # Roles endpoints
    path('roles/', api_roles, name='api_roles'),
    path('roles/<int:pk>/', api_role_detail, name='api_role_detail'),
    
    # Services endpoints
    path('services/', api_services, name='api_services'),
    path('services/<int:pk>/', api_service_detail, name='api_service_detail'),
    
    # Rosters endpoints
    path('rosters/', api_rosters, name='api_rosters'),
    path('rosters/<int:pk>/', api_roster_detail, name='api_roster_detail'),
    path('rosters/generate/', api_generate_roster, name='api_generate_roster'),
    path('rosters/save/', api_save_roster, name='api_save_roster'),
    
    # PDF Export endpoint
    path('generate-roster/', api_export_roster_pdf, name='api_export_roster_pdf'),
    
    # Statistics endpoint
    path('assignment-statistics/', api_assignment_statistics, name='api_assignment_statistics'),
]
