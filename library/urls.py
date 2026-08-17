# library/urls.py
from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    path("", views.index, name="index"),
    path("upload/", views.upload, name="upload"),
    path("record/", views.record, name="record"),
    path("folders/new/", views.create_folder, name="create_folder"),
    path("folders/<int:pk>/samples/", views.folder_samples, name="folder_samples"),
    path("samples/<int:pk>/move/", views.move_sample, name="move_sample"),
    path("samples/<int:pk>/delete/", views.delete_sample, name="delete_sample"),
   
]