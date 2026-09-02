import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from library.models import Sample, SampleTag, Tag, TagSource, TagStatus
from library.storage import local_copy
from .models import AnalysisStatus, DerivedMetadata
from .pipeline import analyse, estimated_tag_names, measured_tag_names

logger = logging.getLogger(__name__)

PIPELINE_FIELDS = [
    "duration_seconds", "sample_rate", "channels", "peaks",
    "bpm", "bpm_confidence", "tonic", "mode", "key_confidence",
    "quality_flags", "pipeline_version",
]


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def analyse_sample(self, sample_id):
    try:
        sample = Sample.objects.select_related("folder__library").get(pk=sample_id)
    except Sample.DoesNotExist:
        logger.warning("analyse_sample: sample %s no longer exists", sample_id)
        return

    meta, _ = DerivedMetadata.objects.get_or_create(sample=sample)
    DerivedMetadata.objects.filter(pk=meta.pk).update(
        status=AnalysisStatus.RUNNING,
        attempts=meta.attempts + 1,
        error_message="",
    )

    try:
        # The pipeline needs a real file on disk. local_copy gives us one
        # whether the audio lives in local media/ or in an S3-style bucket.
        with local_copy(sample.audio_file) as path:
            result = analyse(path)

        with transaction.atomic():
            for field in PIPELINE_FIELDS:
                setattr(meta, field, result[field])
            meta.status = AnalysisStatus.COMPLETE
            meta.analysed_at = timezone.now()
            meta.error_message = ""
            meta.save()

            _write_derived_tags(sample, result)

    except Exception as exc:
        logger.exception("Analysis failed for sample %s", sample_id)
        DerivedMetadata.objects.filter(pk=meta.pk).update(
            status=AnalysisStatus.FAILED,
            error_message=f"{type(exc).__name__}: {exc}"[:1000],
        )
        return

    return {"sample_id": sample_id, "bpm": result["bpm"], "tonic": result["tonic"]}


def _write_derived_tags(sample, result):
    """Container facts are written ACCEPTED — they are measurements. Tempo and
    key are written SUGGESTED, because they are algorithmic estimates and the
    user is the authority on whether they are right."""
    for name in measured_tag_names(result):
        _write_tag(sample, name, TagStatus.ACCEPTED, None)

    for name, confidence in estimated_tag_names(result):
        _write_tag(sample, name, TagStatus.SUGGESTED, round(float(confidence), 3))


def _write_tag(sample, name, status, confidence):
    tag, _ = Tag.objects.get_or_create(
        name=name.lower(), defaults={"kind": Tag.Kind.OBJECTIVE}
    )
    SampleTag.objects.get_or_create(
        sample=sample,
        tag=tag,
        defaults={
            "source": TagSource.DERIVED,
            "status": status,
            "confidence": confidence,
        },
    )