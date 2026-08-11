from django.urls import path
from . import views

app_name = "social"          

urlpatterns = [
    path("", views.index, name="index"),
    path("post/new/", views.create_post, name="create_post"),
]