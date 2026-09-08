from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import ProfileForm, RegisterForm
from attribution.models import CreditRecord
from library.models import Sample
from social.models import Post

from django.views.decorators.vary import vary_on_headers

User = get_user_model()

PROFILE_TABS = ("posts", "samples", "credits")


def register(request):
    if request.user.is_authenticated:
        return redirect("social:index")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            # New accounts land on profile setup, not the library: the
            # profile page renders sensibly with defaults if they skip it,
            # so the redirect is an invitation rather than a gate.
            return redirect(f"{reverse('accounts:profile_setup')}?welcome=1")
    else:
        form = RegisterForm()

    return render(request, "registration/register.html", {"form": form})


@login_required
def profile_setup(request):
    """First-time profile creation and later editing share this view."""
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect("accounts:profile", username=request.user.username)
    else:
        form = ProfileForm(instance=request.user)

    return render(request, "accounts/profile_setup.html", {
        "form": form,
        "is_welcome": request.GET.get("welcome") == "1",
        "active_page": "profile",
    })


@login_required
@vary_on_headers("HX-Request")
def profile(request, username):
    profile_user = get_object_or_404(User, username=username)
    is_own = request.user == profile_user

    tab = request.GET.get("tab", "posts")
    if tab not in PROFILE_TABS:
        tab = "posts"

    context = {
        "profile_user": profile_user,
        "is_own_profile": is_own,
        "tab": tab,
        "active_page": "profile" if is_own else None,
    }

    if tab == "posts":
        # The same annotations the feed applies, so post_card.html renders
        # identically here — like state, counts, and the download count.
        context["posts"] = (
            Post.objects.published()
            .filter(author=profile_user)
            .for_cards(request.user)
            .order_by("-created_at")
        )
    elif tab == "samples":
        context["samples"] = (
            Sample.objects.in_library_of(profile_user)
            .public()
            .committed()
            .select_related("metadata")
            .prefetch_related("sample_tags__tag")
            .annotate(download_count=Count("downloads", distinct=True))
        )
    else:
        # Credits received: every credit against a sample this user owns.
        context["credits"] = (
            CreditRecord.objects
            .filter(sample__folder__library__user=profile_user)
            .select_related("creditor", "sample__metadata")
            .order_by("-created_at")
        )

    if request.headers.get("HX-Request") and not request.headers.get("HX-History-Restore-Request"):
        return render(request, "accounts/partials/profile_panel.html", context)

    return render(request, "accounts/profile.html", context)


@login_required
def settings(request):
    return render(request, "accounts/settings.html", {
        "active_page": "settings",
    })