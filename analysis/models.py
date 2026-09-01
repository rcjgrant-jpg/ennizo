from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

PITCH_CLASSES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


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

    instrument = models.CharField(max_length=50, blank=True)
    instrument_confidence = models.FloatField(null=True, blank=True)
    quality_flags = models.JSONField(default=dict, blank=True)

    analysed_at = models.DateTimeField(null=True, blank=True)
    pipeline_version = models.CharField(max_length=20, blank=True)

    # --- user corrections: kept separate so pipeline output survives ---
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

    # --- effective values ---

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


