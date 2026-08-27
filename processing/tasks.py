import logging
import os
import tempfile

import soundfile as sf
from celery import shared_task
from django.core.files import File

import numpy as np
from scipy.signal import lfilter

from library.models import Sample

logger = logging.getLogger(__name__)

EQ_BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]
EQ_Q = 1.0

# Ai used to assist with helper function implementation

def _peaking_coeffs(freq, sr, gain_db, q):
    """Biquad peaking-EQ coefficients per the Audio EQ Cookbook
    (Bristow-Johnson)"""
    
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * freq / sr
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)

    b = np.array([1 + alpha * A, -2 * cos_w0, 1 - alpha * A])
    a = np.array([1 + alpha / A, -2 * cos_w0, 1 - alpha / A])
    return b / a[0], a / a[0]

def _apply_eq(audio, sr, gains):
    for freq, gain_db in zip(EQ_BANDS, gains):
        if abs(gain_db) < 0.01:
            continue          # flat band: skip, no-op
        b, a = _peaking_coeffs(freq, sr, gain_db, EQ_Q)
        audio = lfilter(b, a, audio, axis=0)
    return audio

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
            
    gains = params.get("gains")
    if gains and any(abs(g) > 0.01 for g in gains):
        audio = _apply_eq(audio, sr, gains)
        
    peak = np.max(np.abs(audio))
    if peak > 1.0:
        audio = audio / peak

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
    
        
    
        
        