from django.urls import path

from . import views

app_name = "social"

urlpatterns = [
    path("", views.index, name="index"),
    path("post/draft/", views.create_draft, name="create_draft"),
    path("post/publish/", views.publish_draft, name="publish_draft"),
    path("post/discard/", views.discard_draft, name="discard_draft"),
    path("post/<int:pk>/state/", views.draft_state, name="draft_state"),
    path("posts/<int:pk>/like/", views.toggle_like, name="toggle_like"),
    path("posts/<int:pk>/comments/", views.post_comments, name="post_comments"),
    path("posts/<int:pk>/comments/add/", views.add_comment, name="add_comment"),
    path("tags/suggest/", views.tag_suggest, name="tag_suggest"),
]