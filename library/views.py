from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import FolderForm, SampleUploadForm

from .models import Folder, Sample, SampleTag, Tag, TagSource, TagStatus

import subprocess
import tempfile
from pathlib import Path

from django.core.files import File
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

@login_required
def index(request):
    folders = (
        Folder.objects
        .filter(library__user=request.user)
        .annotate(sample_count=Count("samples", filter=Q(samples__is_committed=True)))
        .order_by("name")
        
    )

    return render(request, "library/index.html", {
        "folders": folders,
        "folder_form": FolderForm(user=request.user),
        "active_page": "library",
    })

@login_required
def draft_tags(request, pk):
    """Render the composer's tag panel, or act on it and re-render.

    GET and POST share one view because every action ends the same way — the
    panel redrawn from the database. Separate routes would differ only in the
    two lines that mutate a row.
    """
    
    
    sample = get_object_or_404(Sample.objects.in_library_of(request.user), pk=pk)
    action = request.POST.get("action")
    tag_pk = request.POST.get("tag_pk", "")

    if action == "add":
        name = (request.POST.get("tag_name") or "").strip().lower()[:100]
        if name and len(sample.accepted_tags()) < 10:
            
            tag, _ = Tag.objects.get_or_create(
                name=name, defaults={"kind": Tag.Kind.SUBJECTIVE}
            )
            row, created = SampleTag.objects.get_or_create(
                sample=sample, tag=tag,
                defaults={"source": TagSource.USER, "status": TagStatus.ACCEPTED},
            )
            if not created:
                
                row.accept()

    elif action in ("keep", "remove") and tag_pk.isdigit():
        row = get_object_or_404(SampleTag, pk=tag_pk, sample=sample)
        
        row.accept() if action == "keep" else row.reject()
        
    open_raw = request.GET.get("open", "")

    return render(request, "library/partials/draft_tags.html", {
        "sample": sample,
        "open_pk": int(open_raw) if open_raw.isdigit() else 0,
        "adding": request.GET.get("adding") == "1",
    })

@login_required
def folder_samples(request, pk):
    folder = get_object_or_404(Folder, pk=pk, library__user=request.user)

    return render(request, "library/partials/folder_samples.html", {
        "folder": folder,
        "samples": folder.samples.committed().select_related("metadata").prefetch_related("sample_tags__tag"),
        "folders": Folder.objects.filter(library__user=request.user).order_by("name"),
    })
    
@login_required
def move_sample(request, pk):
    sample = get_object_or_404(Sample, pk=pk, folder__library__user=request.user)
    origin = sample.folder

    if request.method == "POST":
        target = get_object_or_404(
            Folder, pk=request.POST.get("folder"), library__user=request.user
        )
        sample.folder = target
        sample.save(update_fields=["folder"])

    return render(request, "library/partials/folder_samples.html", {
        "folder": origin,
        "samples": origin.samples.committed().select_related("metadata").prefetch_related("sample_tags__tag"),
        "folders": Folder.objects.filter(library__user=request.user).order_by("name"),
    })


@login_required
def delete_sample(request, pk):
    sample = get_object_or_404(Sample, pk=pk, folder__library__user=request.user)
    folder = sample.folder

    if request.method == "POST":
        try:
            # File cleanup and draft teardown live in Sample.delete().
            # PROTECT only fires for a published post now, so the error
            # message below is precisely true.
            sample.delete()
            messages.success(request, "Sample deleted.")
        except ProtectedError:
            messages.error(
                request,
                "That sample can't be deleted while it's attached to a post.",
            )

    return render(request, "library/partials/folder_samples.html", {
        "folder": folder,
        "samples": folder.samples.committed().select_related("metadata").prefetch_related("sample_tags__tag"),
        "folders": Folder.objects.filter(library__user=request.user).order_by("name"),
    })


@login_required
def create_folder(request):
    if request.method != "POST":
        return redirect("library:index")

    form = FolderForm(request.POST, user=request.user)
    if form.is_valid():
        folder = form.save(commit=False)
        folder.library = request.user.library
        folder.save()
        messages.success(request, f"Folder “{folder.name}” created.")
    else:
        messages.error(request, form.errors["name"][0])

    return redirect("library:index")


@login_required
def record_sample(request):
    if request.method == "POST":
        blob = request.FILES.get("audio")
        if blob is None:
            return JsonResponse({"error": "No audio was received."}, status=400)
        if blob.size > 100 * 1024 * 1024:
            return JsonResponse(
                {"error": "That recording is too large (100MB maximum)."},
                status=400,
            )

        folder = Folder.objects.filter(
            library__user=request.user,
            pk=request.POST.get("folder"),
        ).first()
        if folder is None:
            return JsonResponse({"error": "Choose a valid folder."}, status=400)

        title = request.POST.get("title", "").strip() or (
            "Recording " + timezone.now().strftime("%Y-%m-%d %H:%M")
        )

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / ("input" + Path(blob.name).suffix)
            dst = Path(tmp) / "output.wav"

            with src.open("wb") as fh:
                for chunk in blob.chunks():
                    fh.write(chunk)

            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(src), str(dst)],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return JsonResponse(
                    {"error": "The recording could not be converted."},
                    status=500,
                )

            with dst.open("rb") as fh:
                with transaction.atomic():
                    sample = Sample(
                        folder=folder,
                        title=title,
                        is_committed=False,
                    )
                    sample.audio_file.save(
                        f"{slugify(title) or 'recording'}.wav",
                        File(fh),
                        save=True,
                    )

        return JsonResponse(
            {"redirect": reverse("analysis:sample_analysis", args=[sample.pk])}
        )

    folders = Folder.objects.filter(library__user=request.user).order_by("name")
    return render(request, "library/record.html", {
        "folders": folders,
        "active_page": "record",
    })

@login_required
@require_POST
def discard_sample(request, pk):
    
    sample = get_object_or_404(
        Sample,
        pk=pk,
        folder__library__user=request.user,
        is_committed=False,
    )
    source = sample.rendered_from
    title = sample.title
    sample.delete()
    messages.info(request, f"“{title}” discarded.")

    if source is not None and source.folder.library.user_id == request.user.pk:
        return redirect("analysis:sample_analysis", pk=source.pk)
    return redirect("library:index")

@login_required
@require_POST
def commit_sample(request, pk):

    sample = get_object_or_404(Sample.objects.in_library_of(request.user), pk=pk)
    sample.is_committed = True
    sample.save(update_fields=["is_committed"])

    if not request.headers.get("HX-Request"):
        return redirect("analysis:sample_analysis", pk=sample.pk)

    return render(request, "library/partials/action_bar.html", {
        "sample": sample,
        "show_edit": True,
    })
        

@login_required
def upload(request):
    if request.method == "POST":
        form = SampleUploadForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                sample = form.save(commit=False)
                sample.is_committed = False
                sample.folder = form.cleaned_data["folder"]
                sample.save()

                for name in form.cleaned_data["tags"]:
                    tag, _ = Tag.objects.get_or_create(name=name)
                    SampleTag.objects.create(
                        sample=sample, tag=tag, source=TagSource.USER
                    )

            return redirect("analysis:sample_analysis", pk=sample.pk)
    else:
        form = SampleUploadForm(user=request.user)

    return render(request, "library/upload.html", {
        "form": form,
        "active_page": "library",
    })