from django.db import models
from django.contrib.auth.models import User

class Sample(models.Model):
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    audio_file = models.FileField(upload_to="samples/")   # the file itself
    is_processed = models.BooleanField(default=False)
