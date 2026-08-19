from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import RegisterForm
from library.models import Sample
from social.models import Post

User = get_user_model()

def register(request):
    if request.user.is_authenticated:
        return redirect("social:index")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("library:index")
    else:
        form = RegisterForm()

    return render(request, "registration/register.html", {"form": form})

def profile(request, username):
    # Navigating here means the composer was left without publishing.
    if request.user.is_authenticated:
        Post.objects.drafts_for(request.user).discard()

    profile_user = get_object_or_404(User, username=username)
    is_own = request.user == profile_user
    samples = (
        Sample.objects
        .in_library_of(profile_user)
        .visible_to(request.user)
        .select_related("metadata")
        .not_drafts()
        .prefetch_related("sample_tags__tag")
    )
    return render(request, "accounts/profile.html", {
        "profile_user": profile_user,
        "samples": samples,
        "is_own_profile": is_own,
        "active_page": "profile" if is_own else None,
    })


@login_required
def settings(request):
    Post.objects.drafts_for(request.user).discard()

    return render(request, "accounts/settings.html", {
        "active_page": "settings",
    })
