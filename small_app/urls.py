from .views import *
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


urlpatterns = [
    # Existing URLs
    path('signup/', signup, name='signup'),
    path('login/', login, name='login'),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('persons/', persons, name='persons'),
    path('persons/<int:pk>/', person_detail, name='person_detail'),
    path('roles/', roles, name='roles'),
    path('roles/<int:pk>/', role_detail, name='role_detail'),
    path('events/', events, name='events'),
    path('events/<int:pk>/', event_detail, name='event_detail'),
    path('rosters/', rosters, name='rosters'),
    path('rosters/save/', save_roster, name='save_roster'),
    # path('rosters/generate/',generate_structured_roster),  # Removed - conflicts with API endpoint
    path('assignments/', assignments, name='assignments'),
    path('assignments/<int:pk>/', assignment_detail, name='assignment_detail'),
    path('availability/status-choices/', get_status, name='status-choices'),
    path('generate-roster/', generate_and_download_roster, name='generate_roster'),
] 