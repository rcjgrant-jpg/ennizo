# library/urls.py
from django.urls import path

from . import views


app_name = "library"

urlpatterns = [
    path("", views.index, name="index"),
    path("upload/", views.upload, name="upload"),
    path("folders/new/", views.create_folder, name="create_folder"),
    path("folders/<int:pk>/samples/", views.folder_samples, name="folder_samples"),
    path("samples/<int:pk>/move/", views.move_sample, name="move_sample"),
    path("samples/<int:pk>/delete/", views.delete_sample, name="delete_sample"),
    path("samples/<int:pk>/commit/", views.commit_sample, name="commit_sample"),
    path("samples/<int:pk>/tags/", views.draft_tags, name="draft_tags"),
    path("record", views.record_sample, name="record"),
    path("samples/<int:pk>/discard/", views.discard_sample, name="discard_sample"),
   
]