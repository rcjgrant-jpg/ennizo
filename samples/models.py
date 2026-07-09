from django.db import models
from django.contrib.auth.models import User


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

class Sample(models.Model):
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    audio_file = models.FileField(upload_to="samples/")   # the file itself
    is_processed = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, through="SampleTag", related_name="samples")

class SampleTag(models.Model):
    sample = models.ForeignKey(Sample, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    source = models.CharField(max_length=10, choices=[("user", "User"), ("ai", "AI")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("sample", "tag")   # a sample can't have the same tag twice