import uuid
from pathlib import Path

from django.db import models
from django.db.models import Q
from django.utils import timezone


def variant_upload_path(instance, filename):
    ext = Path(filename).suffix.lower() or ".wav"
    owner_id = instance.sample.folder.library.user_id
    return f"variants/{owner_id}/{uuid.uuid4().hex}{ext}"


class Operation(models.TextChoices):
    EQ = "eq", "Equalisation"
    NORMALISE = "normalise", "Normalise"
    TRIM = "trim", "Trim silence"
    DENOISE = "denoise", "De-noise"


class VariantStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"


