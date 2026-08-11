# library/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from .forms import SampleUploadForm
from .models import Folder, Sample, SampleTag, Tag, TagSource


@login_required
def index(request):
    samples = (
        Sample.objects
        .in_library_of(request.user)
        .select_related("metadata", "folder")
        .prefetch_related("tags")
    )

    return render(request, "library/index.html", {
        "samples": samples,
        "active_page": "library",
    })


@login_required
def record(request):
    return render(request, "library/record.html", {
        "active_page": "record",
    })


@login_required
def upload(request):
    if request.method == "POST":
        form = SampleUploadForm(request.POST, request.FILES)
        if form.is_valid():
            folder, _ = Folder.objects.get_or_create(
                library__user=request.user,
                name="Unsorted",
                defaults={"library": request.user.library},
            )

            with transaction.atomic():
                sample = form.save(commit=False)
                sample.folder = folder
                sample.save()

                for name in form.cleaned_data["tags"]:
                    tag, _ = Tag.objects.get_or_create(name=name)
                    SampleTag.objects.create(
                        sample=sample, tag=tag, source=TagSource.USER
                    )

            messages.success(request, f"“{sample.title}” uploaded.")
            return redirect("library:index")
    else:
        form = SampleUploadForm()

    return render(request, "library/upload.html", {
        "form": form,
        "active_page": "library",
    })

