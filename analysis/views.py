# analysis/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from library.models import Sample
from social.models import Post

from .models import AnalysisStatus, DerivedMetadata
from .tasks import analyse_sample


# --- helpers -----------------------------------------------------------------

def _get_visible_sample(request, pk):
    """A sample the current viewer is allowed to see, or 404."""
    return get_object_or_404(
        Sample.objects.visible_to(request.user).select_related(
            "metadata", "folder__library__user"
        ),
        pk=pk,
    )


def _get_owned_sample(request, pk):
    """A sample the current viewer owns, or 404. Used by write actions."""
    return get_object_or_404(
        Sample.objects.in_library_of(request.user).select_related("metadata"),
        pk=pk,
    )


def _page_context(request, sample):
    """Everything both the full page and the polled fragment need."""
    try:
        post = sample.post
    except Post.DoesNotExist:
        post = None

    return {
        "sample": sample,
        "metadata": getattr(sample, "metadata", None),
        "post": post,
        "is_owner": sample.folder.library.user_id == request.user.id,
        "active_page": "library",
    }


# --- views -------------------------------------------------------------------

def sample_analysis(request, pk):
    """Full analysis / confirmation page."""
    sample = _get_visible_sample(request, pk)
    return render(request, "analysis/sample_analysis.html", _page_context(request, sample))


def sample_analysis_state(request, pk):
    """Polled fragment. Same context, partial template only."""
    sample = _get_visible_sample(request, pk)
    return render(request, "analysis/_analysis_state.html", _page_context(request, sample))


@login_required
@require_POST
def retry_analysis(request, pk):
    sample = _get_owned_sample(request, pk)

    metadata, _ = DerivedMetadata.objects.get_or_create(sample=sample)
    DerivedMetadata.objects.filter(pk=metadata.pk).update(
        status=AnalysisStatus.PENDING,
        error_message="",
    )
    analyse_sample.delay(sample.pk)

    sample.refresh_from_db()
    if not request.headers.get("HX-Request"):
        return redirect("analysis:sample_analysis", pk=sample.pk)
    return render(request, "analysis/_analysis_state.html", _page_context(request, sample))