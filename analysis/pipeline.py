import logging

import essentia.standard as es
import librosa
import numpy as np
import soundfile as sf

from audio.flags import quality_flags
from audio.waveform import compute_peaks

# Vocabulary and thresholds live on the model (no audio imports there), so
# the web process can use them without loading Essentia. This module is only
# ever imported by the Celery worker.
from .models import MIN_TEMPO_DURATION, PITCH_CLASSES

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.1.0"

ANALYSIS_SR = 22050
TARGET_SR = 44100

# Essentia reports sharps; Ennizo uses flats.
ENHARMONIC = {"C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb"}

# Key detection is delegated to Essentia's KeyExtractor. 'edma' profiles were
# fitted by Faraldo et al. (2016) on electronic dance music, which matches the
# material producers upload here far better than Krumhansl-Kessler, which came
# from probe-tone experiments with Western classical stimuli.
KEY_PROFILE = "edma"
KEY_SR = 44100          # rate the edma profiles were fitted and evaluated at
KEY_MIN_DURATION = 0.5  # seconds; below this a key estimate is meaningless


def _container_facts(path):
    info = sf.info(str(path))
    return {
        "duration_seconds": float(info.duration),
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
    }


def _detect_tempo(y, sr, duration):
    """Returns (bpm, confidence 0-1). Never gates on confidence: the model
    decides whether an estimate is confident enough to suggest as a tag."""
    if duration < MIN_TEMPO_DURATION:
        return None, None

    if sr != TARGET_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=TARGET_SR)
    audio = np.ascontiguousarray(y, dtype=np.float32)

    bpm, beats, beats_conf, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
    if bpm <= 0 or len(beats) < 4:
        return None, None

    return round(float(bpm), 2), round(min(1.0, beats_conf / 3.5), 3)


def _detect_key(y, sr):
    """Returns (tonic 0-11, mode, confidence 0-1), or (None, "", None)."""
    audio = np.asarray(y)
    if audio.ndim > 1:
        audio = librosa.to_mono(audio)
    if audio.size < int(sr * KEY_MIN_DURATION):
        return None, "", None

    peak = float(np.max(np.abs(audio)))
    if peak < 1e-6:
        return None, "", None
    audio = audio / peak

    try:
        if sr != KEY_SR:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=KEY_SR)
        # Essentia requires float32 and contiguous memory; it raises on float64.
        audio = np.nan_to_num(np.ascontiguousarray(audio, dtype=np.float32))
        key, scale, strength = es.KeyExtractor(profileType=KEY_PROFILE, sampleRate=KEY_SR)(audio)
    except Exception:
        logger.exception("Key extraction failed")
        return None, "", None

    key = ENHARMONIC.get(key, key)
    if key not in PITCH_CLASSES:
        logger.warning("Unrecognised key name from Essentia: %r", key)
        return None, "", None

    mode = scale if scale in ("major", "minor") else ""
    return PITCH_CLASSES.index(key), mode, round(float(np.clip(strength, 0.0, 1.0)), 3)


def analyse(path):
    """Run the full deterministic pipeline. Returns a plain dict."""
    facts = _container_facts(path)
    y, sr = librosa.load(str(path), sr=ANALYSIS_SR, mono=True)

    bpm, bpm_conf = _detect_tempo(y, sr, facts["duration_seconds"])
    tonic, mode, key_conf = _detect_key(y, sr)

    return {
        **facts,
        "peaks": compute_peaks(y),
        "bpm": bpm,
        "bpm_confidence": bpm_conf,
        "tonic": tonic,
        "mode": mode,
        "key_confidence": key_conf,
        "quality_flags": quality_flags(y, sr, facts),
        "pipeline_version": PIPELINE_VERSION,
    }


def measured_tag_names(result):
    """Tags read directly from the container. Duration and channel count are
    facts, not estimates, so they need no human ruling. (Tempo and key tags
    are the metadata's business — see DerivedMetadata.estimate_tags.)"""
    names = []
    duration = result.get("duration_seconds") or 0
    if duration < MIN_TEMPO_DURATION:
        names.append("one-shot")
    elif duration <= 30:
        names.append("loop")
    if result.get("channels") == 1:
        names.append("mono")
    return names