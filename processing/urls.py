from django.urls import path

from . import views

app_name = "processing"


urlpatterns = [
    path("", views.editor_home, name="editor_home"),
    path("samples/<int:pk>/edit", views.edit_sample, name="edit_sample"),
]