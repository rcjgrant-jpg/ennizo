# social/views.py
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import render, redirect

from .models import Post, Like
from .forms import PostForm


@login_required
def index(request):
    posts = (
        Post.objects
        .select_related("author", "sample", "sample__metadata")
        .prefetch_related("sample__tags")
        .annotate(
            like_count=Count("likes", distinct=True),
            comment_count=Count("comments", distinct=True),
            liked_by_user=Exists(
                Like.objects.filter(post=OuterRef("pk"), user=request.user)
            ),
        )
    )
    
    form = PostForm(user=request.user) if "compose" in request.GET else None

    return render(request, "social/feed.html", {
        "posts": posts,
        "form": form,
        "active_page": "feed",
    })

    
@login_required
def create_post(request):
    if request.method == "POST":
        form = PostForm(request.POST, user=request.user)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            return redirect("social:index")
    else:
        form = PostForm(user=request.user)

    return render(request, "social/feed.html", {"form": form, "active_page": "feed"})