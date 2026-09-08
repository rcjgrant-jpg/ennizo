import logging
import os
import tempfile

import soundfile as sf
from celery import shared_task
from django.core.files import File

import numpy as np
from scipy.signal import lfilter

from library.models import Sample
from library.storage import local_copy

import pyloudnorm as pyln

logger = logging.getLogger(__name__)

EQ_BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]
EQ_Q = 1.0

# Ai used to assist with helper function implementation

def apply_tame_peaks(y: np.ndarray, sr: int,
                     threshold_db: float = -1.0,
                     ratio: float = 20.0,
                     release_db_per_s: float = 60.0) -> np.ndarray:
    """Attenuate transients above the threshold; audio below it is
    untouched. Expects float audio, shape (n,) mono or (n, channels);
    returns the same shape and dtype.

    Feed-forward peak compressor, implemented directly in numpy. Attack is
    instantaneous (at 20:1 the 0.5 ms attack of the previous pedalboard
    implementation was already effectively a limiter); release is linear in
    dB at ``release_db_per_s``, so a typical few-dB over recovers within
    about 100 ms. Every channel receives the same gain, keyed to the loudest
    channel, so the stereo image is not disturbed. No makeup gain.

    The release is computed without a sample-by-sample loop: a linear-in-dB
    decay from every past peak is the running maximum of
    ``reduction[j] - k * (n - j)``, which rearranges to a cumulative max of
    ``reduction + k * index`` minus ``k * index``.
    """
    x = np.asarray(y, dtype=np.float64)
    if x.size == 0:
        return y

    level = np.abs(x) if x.ndim == 1 else np.max(np.abs(x), axis=1)
    with np.errstate(divide="ignore"):          # log10(0) for silence -> -inf
        level_db = 20.0 * np.log10(level)

    over_db = np.maximum(level_db - threshold_db, 0.0)
    reduction_db = over_db * (1.0 - 1.0 / ratio)

    k = release_db_per_s / sr                    # dB recovered per sample
    idx = np.arange(len(reduction_db), dtype=np.float64)
    smoothed_db = np.maximum.accumulate(reduction_db + k * idx) - k * idx

    gain = 10.0 ** (-smoothed_db / 20.0)
    if x.ndim == 2:
        gain = gain[:, None]
    return (x * gain).astype(np.asarray(y).dtype)

def apply_normalise(y: np.ndarray, sr: int, target_lufs: float = -14.0) -> np.ndarray:
    """Loudness-normalise to the target integrated LUFS. Overs introduced by
    the gain change are handled downstream: tame_peaks if selected, and the
    final peak-safety divide in render_sample regardless."""
    if len(y) < int(0.4 * sr):          # pyloudnorm needs at least one 400 ms block
        return y
    loudness = pyln.Meter(sr).integrated_loudness(y)
    if not np.isfinite(loudness):       # silence or near-silence
        return y
    return pyln.normalize.loudness(y, loudness, target_lufs)

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

    # soundfile reads by path; local_copy provides one whether the source
    # is in local media/ or an S3-style bucket.
    with local_copy(sample.audio_file) as path:
        audio, sr = sf.read(path)

    trim_start = params.get("trim_start")
    trim_end = params.get("trim_end")

    if trim_start is not None and trim_end is not None:
        start_idx = int(round(trim_start * sr))
        end_idx = int(round(trim_end * sr))

        start_idx = max(0, start_idx)
        end_idx = min(len(audio), end_idx)

        if start_idx < end_idx and (start_idx > 0 or end_idx < len(audio)):
            audio = audio[start_idx:end_idx]
            
    if params.get("normalise"):
        audio = apply_normalise(audio, sr)
        
    if params.get("tame_peaks"):
        audio = apply_tame_peaks(audio, sr)
            
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
        suffix = "(preview)" if params.get("preview") else "(edited)"
        new_sample = Sample(
            folder=sample.folder,
            title=f"{sample.title} {suffix}",
            is_public=sample.is_public,
            is_committed=False,
            rendered_from=sample,
            # A render is the same recording processed; its provenance is
            # the source's provenance.
            origin=sample.origin,
            licence=sample.licence,
        )
        # FieldFile.save() goes through the configured storage backend, so
        # this uploads to the bucket in production and writes to media/ locally.
        with open(temp_file_path, "rb") as f:
            new_sample.audio_file.save(f"{sample.pk}_render.wav", File(f), save=True)
    finally:
        os.remove(temp_file_path)

    return {"source": sample_pk, "render": new_sample.pk}