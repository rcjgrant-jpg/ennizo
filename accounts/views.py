from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from library.models import Sample

User = get_user_model()


def profile(request, username):
    profile_user = get_object_or_404(User, username=username)
    samples = (
        Sample.objects
        .in_library_of(profile_user)
        .visible_to(request.user)
        .select_related("metadata")
        .prefetch_related("tags")
    )
    return render(request, "accounts/profile.html", {
        "profile_user": profile_user,
        "samples": samples,
        "is_own_profile": request.user == profile_user,
        "active_page": "profile",
    })


@login_required
def settings(request):
    return render(request, "accounts/settings.html", {
        "active_page": "settings",
    })

