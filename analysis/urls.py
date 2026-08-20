from django.urls import path

from django.urls import path

from . import views

app_name = "analysis"

urlpatterns = [
    path("samples/<int:pk>/", views.sample_analysis, name="sample_analysis"),
    path("samples/<int:pk>/state/", views.sample_analysis_state, name="sample_analysis_state"),
    path("samples/<int:pk>/retry/", views.retry_analysis, name="retry_analysis"),
]