"""Deterministic audio analysis. Pure functions over a file path —
no Django imports, so this is unit-testable in isolation."""

import numpy as np
import librosa
import soundfile as sf
import essentia.standard as es
import logging

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.1.0"

ANALYSIS_SR = 22050
PEAK_BUCKETS = 2000

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Essentia may report flat spellings; the storage format uses sharps.
ENHARMONIC = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "Cb": "B", "Fb": "E", "E#": "F", "B#": "C",
}

# Threshold on Essentia's key strength. Higher than the old margin-based
# threshold because the two measure different things — see _detect_key.
# Calibrated against the labelled evaluation set.
KEY_TAG_THRESHOLD = 0.6

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


def _compute_peaks(y, buckets=PEAK_BUCKETS):
    """Interleaved [min, max, min, max, ...] normalised to -1..1.

    Interleaved rather than absolute values so wavesurfer draws a symmetric
    waveform; absolute values render as a top-half-only shape.
    """
    if y.size == 0:
        return []

    peak = float(np.max(np.abs(y))) or 1.0
    usable = (y.size // buckets) * buckets
    if usable < buckets:
        return [round(float(v) / peak, 4) for v in y]

    frames = y[:usable].reshape(buckets, -1)
    mins = frames.min(axis=1) / peak
    maxs = frames.max(axis=1) / peak

    out = np.empty(buckets * 2, dtype=np.float32)
    out[0::2] = mins
    out[1::2] = maxs
    # Plain Python floats — numpy scalars are not JSON-serialisable.
    return [round(float(v), 4) for v in out]


def _detect_tempo(y, sr, duration):
    """Returns (bpm, confidence). Confidence is derived from how evenly
    spaced the detected beats are: consistent spacing implies a reliable
    estimate, erratic spacing implies the tracker is guessing."""
    if duration < 2.0:
        return None, None

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, units="frames"
    )
    bpm = float(np.atleast_1d(tempo)[0])

    if bpm <= 0 or len(beat_frames) < 4:
        return None, None

    times = librosa.frames_to_time(beat_frames, sr=sr)
    intervals = np.diff(times)
    if intervals.size == 0 or intervals.mean() <= 0:
        return bpm, 0.0

    # Coefficient of variation: 0 is perfectly regular.
    cv = float(intervals.std() / intervals.mean())
    confidence = max(0.0, min(1.0, 1.0 - cv * 2))
    return round(bpm, 2), round(confidence, 3)



def _detect_key(y, sr):
    
    if y is None or np.size(y) == 0:
        return None, "", None

    audio = np.asarray(y)
    if audio.ndim > 1:
        audio = librosa.to_mono(audio)

    if audio.size < int(sr * KEY_MIN_DURATION):
        return None, "", None

    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-6:
        return None, "", None
    audio = audio / peak

    try:
        if sr != KEY_SR:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=KEY_SR)

        # Essentia requires float32 and contiguous memory; it raises on float64.
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)

        extractor = es.KeyExtractor(profileType=KEY_PROFILE, sampleRate=KEY_SR)
        key, scale, strength = extractor(audio)
    except Exception:
        return None, "", None

    key = ENHARMONIC.get(key, key)
    if key not in PITCH_CLASSES:
        logger.warning("Unrecognised key name from Essentia: %r", key)
        return None, "", None

    tonic = PITCH_CLASSES.index(key)
    mode = scale if scale in ("major", "minor") else ""
    confidence = round(float(np.clip(strength, 0.0, 1.0)), 3)

    return tonic, mode, confidence
    


def _quality_flags(y, sr, facts, duration):
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    clipped = int(np.sum(np.abs(y) >= 0.99))
    dc = float(np.mean(y)) if y.size else 0.0

    leading_silence = False
    trailing_silence = False
    if y.size:
        try:
            _, (start, end) = librosa.effects.trim(y, top_db=40)
            leading_silence = (int(start) / sr) > 0.25
            trailing_silence = ((y.size - int(end)) / sr) > 0.25
        except Exception:
            pass

    # bool() at the boundary: NumPy comparisons return np.bool_, which is not
    # JSON-serialisable. Every value leaving this module is a builtin type.
    return {
        "clipping": bool(clipped > (y.size * 0.0001)),
        "very_quiet": bool(peak < 0.1),
        "dc_offset": bool(abs(dc) > 0.01),
        "low_sample_rate": bool(facts["sample_rate"] < 44100),
        "too_short_for_tempo": bool(duration < 2.0),
        "leading_silence": bool(leading_silence),
        "trailing_silence": bool(trailing_silence),
    }


def analyse(path):
    """Run the full deterministic pipeline. Returns a plain dict."""
    facts = _container_facts(path)
    duration = facts["duration_seconds"]

    y, sr = librosa.load(str(path), sr=ANALYSIS_SR, mono=True)

    bpm, bpm_conf = _detect_tempo(y, sr, duration)
    tonic, mode, key_conf = _detect_key(y, sr)

    return {
        **facts,
        "peaks": _compute_peaks(y),
        "bpm": bpm,
        "bpm_confidence": bpm_conf,
        "tonic": tonic,
        "mode": mode or "",
        "key_confidence": key_conf,
        "quality_flags": _quality_flags(y, sr, facts, duration),
        "pipeline_version": PIPELINE_VERSION,
    }


def derived_tag_names(result):
    """Deterministic tags implied by the analysis output. Objective kind —
    each is verifiable from the audio, unlike a user's subjective tag."""
    names = []

    if result.get("bpm") and (result.get("bpm_confidence") or 0) >= 0.4:
        names.append(f"{int(round(result['bpm']))}bpm")

    if result.get("tonic") is not None and (result.get("key_confidence") or 0) >= KEY_TAG_THRESHOLD:
        tonic_name = PITCH_CLASSES[result["tonic"]].lower().replace("#", "sharp")
        names.append(f"{tonic_name}-{result['mode']}" if result["mode"] else tonic_name)

    duration = result.get("duration_seconds") or 0
    if duration < 2:
        names.append("one-shot")
    elif duration <= 30:
        names.append("loop")

    if result.get("channels") == 1:
        names.append("mono")

    return names