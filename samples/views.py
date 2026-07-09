from django.shortcuts import redirect, render
from django.db import Sample
from .tasks import denoise_sample

# samples/views.py
def upload_sample(request):
    sample = Sample.objects.create(
        title=request.POST["title"],
        owner=request.user,
        audio_file=request.FILES["audio"],   # file → storage (S3/local)
    )
    denoise_sample.delay(sample.id)           # job → Redis → a worker later
    return redirect("sample_detail", sample.id)
