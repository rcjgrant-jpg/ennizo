# attribution/urls.py
from django.urls import path

from . import views

app_name = "attribution"

urlpatterns = [
    path("downloads/", views.downloads, name="downloads"),
    path("downloads/<int:pk>/credit/", views.add_credit, name="add_credit"),
    path("samples/<int:pk>/download/", views.download_sample, name="download_sample"),
]
