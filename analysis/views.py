# analysis/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from library.models import Sample
from social.models import Post

from .models import PITCH_CLASSES, AnalysisStatus, DerivedMetadata
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


def _page_context(request, sample, **extra):
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
        "pitch_classes": PITCH_CLASSES,     # key dropdown in the correction control
        "active_page": "library",
        **extra,
    }


def _parse_correction(post):
    """Validate the correction control's three fields. Returns (values, error).
    A blank field means 'keep the measured value' for that field."""
    bpm = post.get("bpm", "").strip()
    tonic = post.get("tonic", "").strip()
    mode = post.get("mode", "").strip()
    try:
        bpm = float(bpm) if bpm else None
        tonic = int(tonic) if tonic else None
    except ValueError:
        return None, "Tempo and key must be numbers."
    if bpm is not None and not 20 <= bpm <= 400:
        return None, "Tempo must be between 20 and 400 BPM."
    if tonic is not None and not 0 <= tonic <= 11:
        return None, "Unknown key."
    if mode and mode not in DerivedMetadata.Mode.values:
        return None, "Unknown mode."
    if mode and tonic is None:
        return None, "Choose a key before choosing major or minor."
    return {"bpm": bpm, "tonic": tonic, "mode": mode}, None


# --- views -------------------------------------------------------------------

def sample_analysis(request, pk):
    """Full analysis / confirmation page."""
    sample = _get_visible_sample(request, pk)
    if not sample.is_committed:
        Sample.objects.filter(pk=pk).update(last_active_at=timezone.now())
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


@login_required
@require_POST
def correct_metadata(request, pk):
    """U1.5: the owner overrides tempo and/or key. The tempo/key tags are
    regenerated from the corrected values (DerivedMetadata.correct), so the
    owner rules once and the tags follow."""
    sample = _get_owned_sample(request, pk)

    values, error = _parse_correction(request.POST)
    if error is None:
        sample.metadata.correct(**values)

    if not request.headers.get("HX-Request"):
        return redirect("analysis:sample_analysis", pk=sample.pk)
    return render(
        request, "analysis/_analysis_state.html",
        _page_context(request, sample, correction_error=error),
    )