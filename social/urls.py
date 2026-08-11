# social/urls.py
from django.urls import path

from . import views

app_name = "social"

urlpatterns = [
    path("", views.index, name="index"),
    path("post/new/", views.create_post, name="create_post"),
    path("posts/<int:pk>/like/", views.toggle_like, name="toggle_like"),
    path("posts/<int:pk>/comments/", views.post_comments, name="post_comments"),
    path("posts/<int:pk>/comments/add/", views.add_comment, name="add_comment"),
    path("tags/suggest/", views.tag_suggest, name="tag_suggest"),
]