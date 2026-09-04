import uuid
from pathlib import Path

from django.core.validators import FileExtensionValidator
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import models
from django.db.models import Q
from django.utils import timezone

from datetime import timedelta



AUDIO_EXTENSIONS = ["wav", "aiff", "aif", "aifc", "flac", "mp3"]


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

    def committed(self):
        
        return self.filter(is_committed=True)

    def with_metadata(self):
        return self.select_related("metadata")


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
        """Only tags the user has accepted — suggestions are not searchable."""
        return self.filter(
            sample_tags__tag__name__in=names,
            sample_tags__status=TagStatus.ACCEPTED,
        ).distinct()

    def analysed(self):
        return self.filter(metadata__status="complete")

    def pending_analysis(self):
        """LEFT JOIN so samples with no metadata row are included."""
        return self.filter(
            Q(metadata__isnull=True) | Q(metadata__status__in=["pending", "failed"])
        )
        
    def discard(self):
        """Delete uncommitted samples in bulk: audio files and any draft
        posts go with them (see Sample.delete, the single teardown path).

        The is_committed filter is the safety net — whatever queryset the
        caller passes, committed samples are never deleted implicitly.
        """
        count = 0
        for sample in self.filter(is_committed=False):
            sample.delete()
            count += 1
        return count

    def reap_uncommitted(self, older_than_minutes=30):
        """Discard abandoned samples: uncommitted and inactive past the lease.

        Carrying a draft post no longer shields a sample — the draft is
        provisional state riding on the sample and is torn down with it.
        """
        cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
        return self.filter(last_active_at__lt=cutoff).discard()


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
    """Where the tag came from — a provenance record, never overwritten."""
    DERIVED = "derived", "Derived"        # deterministic pipeline (bpm, key)
    PREDICTED = "predicted", "Predicted"  # ML classifier output
    USER = "user", "User"
    IMPORTED = "imported", "Imported"


class TagStatus(models.TextChoices):
    """Whether the human has ruled on it — orthogonal to source."""
    SUGGESTED = "suggested", "Suggested"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


class SampleTag(models.Model):
    sample = models.ForeignKey(
        "Sample", on_delete=models.CASCADE, related_name="sample_tags"
    )
    tag = models.ForeignKey("Tag", on_delete=models.CASCADE)
    source = models.CharField(max_length=20, choices=TagSource.choices)
    status = models.CharField(
        max_length=20, choices=TagStatus.choices, default=TagStatus.ACCEPTED
    )
    confidence = models.FloatField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "tag"], name="unique_tag_per_sample"
            )
        ]
        ordering = ["-confidence", "tag__name"]

    def __str__(self):
        return f"{self.sample_id} → {self.tag_id}"

    def accept(self):
        self.status = TagStatus.ACCEPTED
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at"])

    def reject(self):
        self.status = TagStatus.REJECTED
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at"])

    @property
    def is_machine_generated(self):
        return self.source in (TagSource.DERIVED, TagSource.PREDICTED)


class Sample(models.Model):
    folder = models.ForeignKey(
        Folder, on_delete=models.PROTECT, related_name="samples"
    )
    title = models.CharField(max_length=255)
    audio_file = models.FileField(
        upload_to=sample_upload_path,
        validators=[
            FileExtensionValidator(
                allowed_extensions=AUDIO_EXTENSIONS
            )
        ],
    )
    
    is_public = models.BooleanField(default=False)          # U2.7
    note = models.TextField(blank=True)                     # U2.6
    created_at = models.DateTimeField(auto_now_add=True)
    is_committed = models.BooleanField(default=True)
    last_active_at = models.DateTimeField(auto_now_add=True)

    tags = models.ManyToManyField(
        "Tag", through="SampleTag", related_name="samples"
    )
    
    rendered_from = models.ForeignKey(
    "self",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="renders",
    )

    objects = SampleQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def owner(self):
        return self.folder.library.user
    
    @property
    def has_published_post(self): 
        post = getattr(self, "post", None)
        return bool(post and post.is_published)

    @property
    def has_draft_post(self):
        # getattr() works here because a reverse one-to-one raises
        # RelatedObjectDoesNotExist, which subclasses AttributeError.
        post = getattr(self, "post", None)
        return bool(post and not post.is_published)

    def accepted_tags(self):
        """Tags the user has confirmed, or has not objected to.

        Filtered in Python rather than with .filter() so that a
        prefetch_related("sample_tags__tag") is reused. A .filter() on a
        related manager always issues a fresh query, which would mean one
        query per sample on the feed and library pages.
        """
        return [st for st in self.sample_tags.all()
                if st.status == TagStatus.ACCEPTED]

    def suggested_tags(self):
        """Machine suggestions awaiting a human ruling. See accepted_tags."""
        return [st for st in self.sample_tags.all()
                if st.status == TagStatus.SUGGESTED]

    def derived_bpm(self):
        meta = getattr(self, "metadata", None)
        if meta is None or not meta.is_analysed:
            return None
        return meta.effective_bpm
    
    def delete(self, *args, **kwargs):
        """The single teardown path for a sample.

        Every deletion route — the analysis-page discard button, the library
        delete, the reaper, the composer's supersede — ends here, so file
        cleanup and draft teardown are written once.
        """
        post = getattr(self, "post", None)
        if post is not None and not post.is_published:
            post.delete()
        self.audio_file.delete(save=False)
        return super().delete(*args, **kwargs)