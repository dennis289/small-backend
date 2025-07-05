from .views import *
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('signup/', signup, name='signup'),
    path('login/', login, name='login'),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('persons/', persons, name='persons'),
    path('persons/<int:pk>/', person_detail, name='person_detail'),
    path('roles/', roles, name='roles'),
    path('roles/<int:pk>/', role_detail, name='role_detail'),
    path('services/', services, name='services'),
    path('services/<int:pk>/', service_detail, name='service_detail'),
    path('rosters/', rosters, name='rosters'),
    path('rosters/<int:pk>/', roster_detail, name='roster_detail'),
    path('assignments/', assignments, name='assignments'),
    path('assignments/<int:pk>/', assignment_detail, name='assignment_detail'),
    path('availability/', availability, name='availability'),
]