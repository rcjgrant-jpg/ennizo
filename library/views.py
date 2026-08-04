from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Sample


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



