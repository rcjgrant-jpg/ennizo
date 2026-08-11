import uuid
from pathlib import Path

from django.db import models
from django.utils import timezone

from django.db.models import Q


from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import models
from django.core.validators import FileExtensionValidator


def sample_upload_path(instance, filename):
    """Partition uploads by owner and date; randomise the stored filename."""
    ext = Path(filename).suffix.lower()
    owner_id = instance.folder.library.user_id
    stamp = instance.created_at or timezone.now()
    return f"samples/{owner_id}/{stamp:%Y/%m}/{uuid.uuid4().hex}{ext}"

class SampleQuerySet(models.QuerySet):
    
    def public(self):
        return self.filter(is_public=True)

    def in_library_of(self, user):
        return self.filter(folder__library__user=user)

    def visible_to(self, user):
        if not user.is_authenticated:
            return self.public()
        return self.filter(Q(is_public=True) | Q(folder__library__user=user))

    def search(self, keyword):
        """Full-text over title, note and tag names (U3.8)."""
        vector = (
            SearchVector("title", weight="A")
            + SearchVector("note", weight="C")
            + SearchVector("tags__name", weight="B")
        )
        query = SearchQuery(keyword)
        return (
            self.annotate(rank=SearchRank(vector, query))
            .filter(rank__gt=0.01)
            .order_by("-rank")
            .distinct()
        )

    def with_metadata(self):
        return self.select_related("metadata")

    def bpm_between(self, low, high):
        """Honours the user override where one exists (U3.1)."""
        return self.annotate(
            effective_bpm=models.functions.Coalesce(
                "metadata__bpm_override", "metadata__bpm"
            )
        ).filter(effective_bpm__gte=low, effective_bpm__lte=high)

    def in_key(self, tonic, mode=None):
        qs = self.annotate(
            effective_tonic=models.functions.Coalesce(
                "metadata__tonic_override", "metadata__tonic"
            )
        ).filter(effective_tonic=tonic)
        if mode:
            qs = qs.annotate(
                effective_mode=models.functions.Coalesce(
                    "metadata__mode_override", "metadata__mode"
                )
            ).filter(effective_mode=mode)
        return qs

    def tagged(self, *names):
        return self.filter(tags__name__in=names).distinct()

    def analysed(self):
        return self.filter(metadata__analysed_at__isnull=False)

    def pending_analysis(self):
        return self.filter(metadata__analysed_at__isnull=True)


class Folder(models.Model):
    library = models.ForeignKey(
        "accounts.Library", on_delete=models.CASCADE, related_name="folders"
    )
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["library", "name"], name="unique_folder_name_per_library"
            )
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name



class Tag(models.Model):
    class Kind(models.TextChoices):
        OBJECTIVE = "objective", "Objective"
        SUBJECTIVE = "subjective", "Subjective"
        
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
    
class TagSource(models.TextChoices):
    DERIVED = "derived", "Derived"
    USER = "user", "User"
    IMPORTED = "imported", "Imported"
    
   # user correction, separate field
    
class SampleTag(models.Model):
    sample = models.ForeignKey("Sample", on_delete=models.CASCADE, related_name="sample_tags")
    tag = models.ForeignKey("Tag", on_delete=models.CASCADE)
    source = models.CharField(max_length=20, choices=TagSource.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "tag"], name="unique_tag_per_sample"
            )
        ]

    def __str__(self):
        return f"{self.sample_id} → {self.tag_id}"

class Sample(models.Model):
    folder = models.ForeignKey(
        Folder, on_delete=models.PROTECT, related_name="samples"
    )
    title = models.CharField(max_length=255)
    audio_file = models.FileField(
        upload_to=sample_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=["wav", "mp3", "aiff", "flac"])],
    )
    is_public = models.BooleanField(default=False)          # U2.7
    note = models.TextField(blank=True)                     # U2.6
    created_at = models.DateTimeField(auto_now_add=True)

    tags = models.ManyToManyField(
        "Tag", through="SampleTag", related_name="samples"
    )

    objects = SampleQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def owner(self):
        return self.folder.library.user

    def derived_bpm(self):
        meta = getattr(self, "metadata", None)
        if meta is None or meta.analysed_at is None:
            return None
        return meta.bpm_override if meta.bpm_override is not None else meta.bpm
            
