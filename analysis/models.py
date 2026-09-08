import re

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

# --- vocabulary shared by the pipeline (worker) and the views (web) ---------
# This module has no audio imports, so the web process can use everything
# here without loading librosa or Essentia. pipeline.py imports from here.

PITCH_CLASSES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

MIN_TEMPO_DURATION = 2.0   # seconds; shorter clips get no tempo estimate and tag as one-shot

# Confidence gates for the two estimate tags. Below these the pipeline stays
# silent rather than suggesting something it is unsure of (U1.4).
BPM_TAG_THRESHOLD = 0.4
KEY_TAG_THRESHOLD = 0.6    # Essentia key strength; calibrated on the labelled set

_BPM_TAG_RE = re.compile(r"^\d+bpm$")


def tempo_tag_name(bpm):
    return f"{int(round(bpm))}bpm"


def key_tag_name(tonic, mode=""):
    tonic_name = PITCH_CLASSES[tonic].replace("b", "flat").lower()
    return f"{tonic_name}-{mode}" if mode else tonic_name


_KEY_TAG_NAMES = frozenset(
    key_tag_name(t, m) for t in range(12) for m in ("", "major", "minor")
)


def is_estimate_tag_name(name):
    """True for names that encode tempo or key — the tags the metadata owns."""
    return bool(_BPM_TAG_RE.match(name)) or name in _KEY_TAG_NAMES


class AnalysisStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"


class DerivedMetadata(models.Model):
    class Mode(models.TextChoices):
        MAJOR = "major", "Major"
        MINOR = "minor", "Minor"

    sample = models.OneToOneField(
        "library.Sample", on_delete=models.CASCADE, related_name="metadata"
    )

    # --- job state ---
    status = models.CharField(
        max_length=20, choices=AnalysisStatus.choices,
        default=AnalysisStatus.PENDING, db_index=True,
    )
    error_message = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    # --- container facts ---
    duration_seconds = models.FloatField(null=True, blank=True)
    sample_rate = models.PositiveIntegerField(null=True, blank=True)
    channels = models.PositiveSmallIntegerField(null=True, blank=True)

    # Pre-computed waveform for wavesurfer.js: interleaved min/max pairs,
    # normalised to -1..1. Computed once at ingest so the browser never has
    # to download and decode the full file to draw the waveform.
    peaks = models.JSONField(default=list, blank=True)

    # --- pipeline output: never user-writable ---
    bpm = models.FloatField(null=True, blank=True)
    bpm_confidence = models.FloatField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    tonic = models.SmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(11)],
    )
    mode = models.CharField(max_length=10, choices=Mode.choices, blank=True)
    key_confidence = models.FloatField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    quality_flags = models.JSONField(default=dict, blank=True)

    analysed_at = models.DateTimeField(null=True, blank=True)
    pipeline_version = models.CharField(max_length=20, blank=True)

    # --- user corrections: kept separate so pipeline output survives (U1.5) ---
    bpm_override = models.FloatField(null=True, blank=True)
    tonic_override = models.SmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(11)],
    )
    mode_override = models.CharField(max_length=10, choices=Mode.choices, blank=True)
    corrected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "derived metadata"
        constraints = [
            models.CheckConstraint(
                condition=Q(tonic__isnull=True) | Q(tonic__range=(0, 11)),
                name="tonic_in_pitch_class_range",
            ),
            models.CheckConstraint(
                condition=Q(tonic_override__isnull=True)
                | Q(tonic_override__range=(0, 11)),
                name="tonic_override_in_pitch_class_range",
            ),
            models.CheckConstraint(
                condition=Q(bpm__isnull=True) | Q(bpm__gt=0),
                name="bpm_positive",
            ),
            models.CheckConstraint(
                condition=Q(bpm_override__isnull=True) | Q(bpm_override__gt=0),
                name="bpm_override_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["bpm"]),
            models.Index(fields=["tonic", "mode"]),
            models.Index(fields=["analysed_at"]),
        ]

    def __str__(self):
        return f"Metadata for sample {self.sample_id}"

    # --- effective values: the owner's correction wins over the estimate ---

    @property
    def effective_bpm(self):
        return self.bpm_override if self.bpm_override is not None else self.bpm

    @property
    def effective_tonic(self):
        return self.tonic_override if self.tonic_override is not None else self.tonic

    @property
    def effective_mode(self):
        return self.mode_override or self.mode

    # --- state ---

    @property
    def is_analysed(self):
        return self.status == AnalysisStatus.COMPLETE

    @property
    def is_running(self):
        return self.status in (AnalysisStatus.PENDING, AnalysisStatus.RUNNING)

    @property
    def has_failed(self):
        return self.status == AnalysisStatus.FAILED

    @property
    def is_pitched(self):
        return self.is_analysed and self.effective_tonic is not None

    @property
    def has_tempo(self):
        return self.is_analysed and self.effective_bpm is not None

    @property
    def is_corrected(self):
        return (
            self.bpm_override is not None
            or self.tonic_override is not None
            or bool(self.mode_override)
        )

    # --- display ---

    @property
    def key_display(self):
        if not self.is_pitched:
            return ""
        name = PITCH_CLASSES[self.effective_tonic]
        return f"{name} {self.effective_mode}" if self.effective_mode else name

    @property
    def bpm_display(self):
        return f"{self.effective_bpm:.1f}" if self.has_tempo else ""

    @property
    def duration_display(self):
        if self.duration_seconds is None:
            return ""
        minutes, seconds = divmod(int(self.duration_seconds), 60)
        return f"{minutes}:{seconds:02d}"

    @property
    def quality_warnings(self):
        """Human-readable list for the analysis page."""
        labels = {
            "clipping": "Clipping detected",
            "very_quiet": "Very low level",
            "dc_offset": "DC offset present",
            "leading_silence": "Silence at start",
            "trailing_silence": "Silence at end",
            "low_sample_rate": "Below 44.1 kHz",
            "too_short_for_tempo": "Too short for tempo detection",
        }
        return [labels[k] for k, v in self.quality_flags.items() if v and k in labels]

    # --- tempo/key tags: derived from this row, never edited directly ------

    def correct(self, *, bpm=None, tonic=None, mode=""):
        """Record the owner's ruling on tempo and key (U1.5).

        Overrides sit beside the pipeline values rather than replacing them,
        so the measurement survives. The tempo/key tags are then regenerated
        from the effective values: the owner corrects the number once and the
        tags follow (S4).
        """
        self.bpm_override = bpm
        self.tonic_override = tonic
        self.mode_override = mode or ""
        self.corrected_at = timezone.now()
        self.save(update_fields=[
            "bpm_override", "tonic_override", "mode_override", "corrected_at",
        ])
        self.sync_estimate_tags()

    def estimate_tags(self):
        """(name, source, status, confidence) for each tempo/key tag this
        sample should carry. A corrected value is the owner's ruling and is
        never confidence-gated; a pipeline estimate is a gated suggestion."""
        from library.models import TagSource, TagStatus

        wanted = []
        if self.bpm_override is not None:
            wanted.append((tempo_tag_name(self.bpm_override),
                           TagSource.USER, TagStatus.ACCEPTED, None))
        elif self.bpm and (self.bpm_confidence or 0) >= BPM_TAG_THRESHOLD:
            wanted.append((tempo_tag_name(self.bpm),
                           TagSource.DERIVED, TagStatus.SUGGESTED, self.bpm_confidence))

        if self.tonic_override is not None:
            wanted.append((key_tag_name(self.tonic_override, self.mode_override),
                           TagSource.USER, TagStatus.ACCEPTED, None))
        elif self.tonic is not None and (self.key_confidence or 0) >= KEY_TAG_THRESHOLD:
            wanted.append((key_tag_name(self.tonic, self.mode),
                           TagSource.DERIVED, TagStatus.SUGGESTED, self.key_confidence))
        return wanted

    def sync_estimate_tags(self):
        """Make the sample's tempo/key tags match estimate_tags().

        Called after analysis and after a correction. Stale estimate tags are
        deleted, not marked rejected: the pipeline value is still on this row,
        and a '118bpm' beside a corrected '124bpm' is exactly the contradiction
        a correction exists to remove. Tags the user typed are never touched.
        """
        from library.models import SampleTag, Tag

        wanted = {name: (src, status, conf)
                  for name, src, status, conf in self.estimate_tags()}

        for st in SampleTag.objects.filter(sample=self.sample).select_related("tag"):
            if not is_estimate_tag_name(st.tag.name):
                continue
            if st.tag.name not in wanted:
                st.delete()
                continue
            src, status, conf = wanted.pop(st.tag.name)
            if (st.source, st.status, st.confidence) != (src, status, conf):
                st.source, st.status, st.confidence = src, status, conf
                st.save(update_fields=["source", "status", "confidence"])

        for name, (src, status, conf) in wanted.items():
            tag, _ = Tag.objects.get_or_create(
                name=name, defaults={"kind": Tag.Kind.OBJECTIVE}
            )
            SampleTag.objects.create(
                sample=self.sample, tag=tag, source=src, status=status,
                confidence=None if conf is None else round(float(conf), 3),
            )