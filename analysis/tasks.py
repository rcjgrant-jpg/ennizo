import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from library.models import Sample, SampleTag, Tag, TagSource, TagStatus
from library.storage import local_copy
from .models import AnalysisStatus, DerivedMetadata

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
        # Imported here rather than at module level: this module is loaded by
        # every process at startup (the web workers included, via
        # analysis.signals), but only the Celery worker ever runs the
        # pipeline. Deferring the import keeps librosa and Essentia — several
        # hundred MB resident — out of the web process entirely.
        from .pipeline import analyse, measured_tag_names

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

            # Container facts are measurements: written accepted.
            for name in measured_tag_names(result):
                tag, _ = Tag.objects.get_or_create(
                    name=name, defaults={"kind": Tag.Kind.OBJECTIVE}
                )
                SampleTag.objects.get_or_create(
                    sample=sample, tag=tag,
                    defaults={"source": TagSource.DERIVED, "status": TagStatus.ACCEPTED},
                )

            # Tempo and key are estimates: the metadata row owns those tags,
            # which also means a re-analysis never overrides an owner's correction.
            meta.sync_estimate_tags()

    except Exception as exc:
        logger.exception("Analysis failed for sample %s", sample_id)
        DerivedMetadata.objects.filter(pk=meta.pk).update(
            status=AnalysisStatus.FAILED,
            error_message=f"{type(exc).__name__}: {exc}"[:1000],
        )
        return

    return {"sample_id": sample_id, "bpm": result["bpm"], "tonic": result["tonic"]}