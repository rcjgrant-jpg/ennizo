from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from library.models import Sample

from .forms import CreditForm
from .models import CreditRecord, DownloadRecord


def _downloadable(sample, user):
    """A sample may be fetched by its owner, or by anyone it has been shown
    to: marked public, or carried into the feed on a published post.

    Publishing a post already exposes the audio for streaming (the player
    reads the file URL), so allowing download for posted samples widens
    nothing — it just makes the existing exposure honest.
    """
    return (
        sample.owner == user
        or sample.is_public
        or sample.has_published_post
    )


def _entry_context(request, record):
    """Context for one downloads-page entry, including the viewer's own
    credits against that sample so the entry can list them after submission."""
    record.sample.my_credits = list(
        CreditRecord.objects.filter(creditor=request.user, sample=record.sample)
    )
    return {"record": record}


@login_required
def download_sample(request, pk):
    sample = get_object_or_404(
        Sample.objects.select_related("folder__library__user"), pk=pk
    )

    if not _downloadable(sample, request.user):
        raise Http404

    # Downloading your own sample is allowed but recorded for no one —
    # the count means "how many other people have this".
    if sample.owner != request.user:
        DownloadRecord.objects.get_or_create(
            downloader=request.user, sample=sample
        )

    # The stored filename is a UUID (see sample_upload_path); hand the
    # browser something meaningful instead.
    ext = Path(sample.audio_file.name).suffix
    filename = f"{slugify(sample.title) or 'sample'}{ext}"
    return FileResponse(
        sample.audio_file.open("rb"), as_attachment=True, filename=filename
    )


@login_required
def downloads(request):
    records = (
        DownloadRecord.objects
        .filter(downloader=request.user)
        .select_related("sample__folder__library__user")
        .prefetch_related(
            Prefetch(
                "sample__credits",
                queryset=CreditRecord.objects.filter(creditor=request.user),
                to_attr="my_credits",
            )
        )
    )
    return render(request, "attribution/downloads.html", {
        "records": records,
        "active_page": "downloads",
    })


@login_required
@require_POST
def add_credit(request, pk):
    record = get_object_or_404(
        DownloadRecord.objects.select_related("sample__folder__library__user"),
        pk=pk,
        downloader=request.user,
    )
    form = CreditForm(request.POST)

    if form.is_valid():
        credit = form.save(commit=False)
        credit.creditor = request.user
        credit.sample = record.sample
        credit.save()
        form = None  # collapse the dropdown; entry re-renders with the credit

    context = _entry_context(request, record)
    context["form"] = form
    return render(
        request, "attribution/partials/download_entry.html", context
    )