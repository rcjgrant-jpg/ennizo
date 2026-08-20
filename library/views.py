# library/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import FolderForm, SampleUploadForm
from social.models import Post

from .models import Folder, Sample, SampleTag, Tag, TagSource, TagStatus


@login_required
def index(request):
    # Navigating here means the composer was left without publishing.
    Post.objects.drafts_for(request.user).discard()

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
            sample.audio_file.delete(save=False)
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
def record(request):
    return render(request, "library/record.html", {
        "active_page": "record",
    })


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

            messages.success(request, f"“{sample.title}” uploaded.")
            return redirect("analysis:sample_analysis", pk=sample.pk)
    else:
        form = SampleUploadForm(user=request.user)

    return render(request, "library/upload.html", {
        "form": form,
        "active_page": "library",
    })