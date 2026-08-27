import logging
import os
import tempfile

import soundfile as sf
from celery import shared_task
from django.core.files import File

from library.models import Sample

logger = logging.getLogger(__name__)


@shared_task
def render_sample(sample_pk, params):
    try:
        sample = Sample.objects.select_related("folder__library").get(pk=sample_pk)
    except Sample.DoesNotExist:
        logger.warning("render_sample: sample %s no longer exists", sample_pk)
        return

    audio, sr = sf.read(sample.audio_file.path)

    trim_start = params.get("trim_start")
    trim_end = params.get("trim_end")

    if trim_start is not None and trim_end is not None:
        start_idx = int(round(trim_start * sr))
        end_idx = int(round(trim_end * sr))

        start_idx = max(0, start_idx)
        end_idx = min(len(audio), end_idx)

        if start_idx < end_idx and (start_idx > 0 or end_idx < len(audio)):
            audio = audio[start_idx:end_idx]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        temp_file_path = temp_file.name

    sf.write(temp_file_path, audio, sr)

    try:
        new_sample = Sample(
            folder=sample.folder,
            title=f"{sample.title} (edited)",
            is_public=sample.is_public,
            is_committed=False,
            rendered_from=sample,
        )
        with open(temp_file_path, "rb") as f:
            new_sample.audio_file.save(f"{sample.pk}_render.wav", File(f), save=True)
    finally:
        os.remove(temp_file_path)

    return {"source": sample_pk, "render": new_sample.pk}
    
        
    
        
        