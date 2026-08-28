from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("u/<str:username>/", views.profile, name="profile"),
    path("profile/edit/", views.profile_setup, name="profile_setup"),
    path("settings/", views.settings, name="settings"),
    path("register/", views.register, name="register"),
]
