from django.shortcuts import redirect, render
from .models import Sample
from .tasks import denoise_sample
from django.contrib.auth.decorators import login_required


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

def upload_sample(request):
    sample = Sample.objects.create(
        title=request.POST["title"],
        owner=request.user,
        audio_file=request.FILES["audio"],   # file → storage (S3/local)
    )
    denoise_sample.delay(sample.id)           # job → Redis → a worker later
    return redirect("sample_detail", sample.id)


