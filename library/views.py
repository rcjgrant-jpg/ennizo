# library/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from .forms import FolderForm, SampleUploadForm
from .models import Folder, Sample, SampleTag, Tag, TagSource


@login_required
def index(request):
    folders = (
        Folder.objects
        .filter(library__user=request.user)
        .annotate(sample_count=Count("samples"))
        .order_by("name")
    )

    return render(request, "library/index.html", {
        "folders": folders,
        "folder_form": FolderForm(user=request.user),
        "active_page": "library",
    })


@login_required
def folder_samples(request, pk):
    folder = get_object_or_404(Folder, pk=pk, library__user=request.user)

    return render(request, "library/partials/folder_samples.html", {
        "folder": folder,
        "samples": folder.samples.select_related("metadata").prefetch_related("tags"),
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
        "samples": origin.samples.select_related("metadata").prefetch_related("tags"),
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
        "samples": folder.samples.select_related("metadata").prefetch_related("tags"),
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
def upload(request):
    if request.method == "POST":
        form = SampleUploadForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                sample = form.save(commit=False)
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
