from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("u/<str:username>/", views.profile, name="profile"),
    path("settings/", views.settings, name="settings"),
    path("register/", views.register, name="register"),
]