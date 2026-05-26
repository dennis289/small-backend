from django.urls import path
from . import views

urlpatterns = [
    # Generate a new roster for a date
    path('generate/', views.generate_roster_view, name='scheduling_generate'),

    # Wipe and regenerate a roster for a specific date
    path('roster/<str:date_str>/regenerate/', views.regenerate_roster_view, name='scheduling_regenerate'),

    # Get or delete all saved roster entries for a specific date
    path('roster/<str:date_str>/', views.roster_for_date_view, name='scheduling_roster_for_date'),
    path('roster/<str:date_str>/delete/', views.delete_roster_for_date_view, name='scheduling_delete_roster'),

    # Assignment statistics
    path('statistics/', views.roster_statistics_view, name='scheduling_statistics'),

    # Export a roster as PDF
    path('export/pdf/', views.export_roster_pdf_view, name='scheduling_export_pdf'),
]
