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


class ProcessedVariant(models.Model):
    """A processed rendering of a Sample. The original audio_file on Sample
    is immutable; every operation produces a new variant instead (S1)."""

    sample = models.ForeignKey(
        "library.Sample", on_delete=models.CASCADE, related_name="variants"
    )
    # What this operation was applied to. Null means the original.
    source_variant = models.ForeignKey(
        "self", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="derived_variants",
    )

    operation = models.CharField(max_length=20, choices=Operation.choices)
    # Exact parameters applied, so any variant is reproducible from its record.
    params = models.JSONField(default=dict, blank=True)

    audio_file = models.FileField(
        upload_to=variant_upload_path, null=True, blank=True
    )
    duration_seconds = models.FloatField(null=True, blank=True)
    peaks = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=20, choices=VariantStatus.choices,
        default=VariantStatus.PENDING, db_index=True,
    )
    error_message = models.TextField(blank=True)

    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample"],
                condition=Q(is_current=True),
                name="unique_current_variant_per_sample",
            )
        ]

    def __str__(self):
        return f"{self.get_operation_display()} of sample {self.sample_id}"

    @property
    def is_complete(self):
        return self.status == VariantStatus.COMPLETE

    def make_current(self):
        """Atomically demote any existing current variant and promote this one."""
        from django.db import transaction

        with transaction.atomic():
            ProcessedVariant.objects.filter(
                sample=self.sample, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
            self.is_current = True
            self.completed_at = self.completed_at or timezone.now()
            self.save(update_fields=["is_current", "completed_at"])
