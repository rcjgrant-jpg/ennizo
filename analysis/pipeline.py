import numpy as np
import librosa
import soundfile as sf
import essentia.standard as es
import logging
from audio.waveform import compute_peaks
from audio.flags import quality_flags

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.1.0"

ANALYSIS_SR = 22050


PITCH_CLASSES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

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

HOP_LENGTH = 512

TARGET_SR = 44100 

def _container_facts(path):
    info = sf.info(str(path))
    return {
        "duration_seconds": float(info.duration),
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
    }


# def _compute_peaks(y, buckets=PEAK_BUCKETS):
#     """Interleaved [min, max, min, max, ...] normalised to -1..1.

#     Interleaved rather than absolute values so wavesurfer draws a symmetric
#     waveform; absolute values render as a top-half-only shape.
#     """
#     if y.size == 0:
#         return []

#     peak = float(np.max(np.abs(y))) or 1.0
#     usable = (y.size // buckets) * buckets
#     if usable < buckets:
#         return [round(float(v) / peak, 4) for v in y]

#     frames = y[:usable].reshape(buckets, -1)
#     mins = frames.min(axis=1) / peak
#     maxs = frames.max(axis=1) / peak

#     out = np.empty(buckets * 2, dtype=np.float32)
#     out[0::2] = mins
#     out[1::2] = maxs
#     # Plain Python floats — numpy scalars are not JSON-serialisable.
#     return [round(float(v), 4) for v in out]


def _detect_tempo(y, sr, duration):
    """Returns (bpm, confidence in 0-1)."""
    if duration < 2.0:
        return None, None

    if sr != TARGET_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=TARGET_SR)

    audio = np.ascontiguousarray(y, dtype=np.float32)

    extractor = es.RhythmExtractor2013(method="multifeature")
    bpm, beats, beats_conf, _, _ = extractor(audio)

    if bpm <= 0 or len(beats) < 4:
        return None, None

    confidence = min(1.0, beats_conf / 3.5)
    if confidence < 0.3:
        return round(float(bpm), 2), round(confidence, 3)  # flag as unsure

    return round(float(bpm), 2), round(confidence, 3)



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

    if key not in PITCH_CLASSES:
        logger.warning("Unrecognised key name from Essentia: %r", key)
        return None, "", None

    tonic = PITCH_CLASSES.index(key)
    mode = scale if scale in ("major", "minor") else ""
    confidence = round(float(np.clip(strength, 0.0, 1.0)), 3)

    return tonic, mode, confidence
    


# def _quality_flags(y, sr, facts, duration):
#     peak = float(np.max(np.abs(y))) if y.size else 0.0
#     clipped = int(np.sum(np.abs(y) >= 0.99))
#     dc = float(np.mean(y)) if y.size else 0.0

#     leading_silence = False
#     trailing_silence = False
#     if y.size:
#         try:
#             _, (start, end) = librosa.effects.trim(y, top_db=40)
#             leading_silence = (int(start) / sr) > 0.25
#             trailing_silence = ((y.size - int(end)) / sr) > 0.25
#         except Exception:
#             pass

#     # bool() at the boundary: NumPy comparisons return np.bool_, which is not
#     # JSON-serialisable. Every value leaving this module is a builtin type.
#     return {
#         "clipping": bool(clipped > (y.size * 0.0001)),
#         "very_quiet": bool(peak < 0.1),
#         "dc_offset": bool(abs(dc) > 0.01),
#         "low_sample_rate": bool(facts["sample_rate"] < 44100),
#         "too_short_for_tempo": bool(duration < 2.0),
#         "leading_silence": bool(leading_silence),
#         "trailing_silence": bool(trailing_silence),
#     }


def analyse(path):
    """Run the full deterministic pipeline. Returns a plain dict."""
    facts = _container_facts(path)
    duration = facts["duration_seconds"]

    y, sr = librosa.load(str(path), sr=ANALYSIS_SR, mono=True)

    bpm, bpm_conf = _detect_tempo(y, sr, duration)
    tonic, mode, key_conf = _detect_key(y, sr)

    return {
        **facts,
        "peaks": compute_peaks(y),
        "bpm": bpm,
        "bpm_confidence": bpm_conf,
        "tonic": tonic,
        "mode": mode or "",
        "key_confidence": key_conf,
        "quality_flags": quality_flags(y, sr, facts, duration),
        "pipeline_version": PIPELINE_VERSION,
    }


def estimated_tag_names(result):
    """Tags inferred by an algorithm, not read from the file.

    Returns (name, confidence) pairs. Tempo and key are estimates gated behind
    confidence thresholds; testing showed key detection in particular to be
    unreliable on real material, so these are written as suggestions for the
    user to confirm rather than as settled facts.
    """
    pairs = []

    bpm_confidence = result.get("bpm_confidence") or 0
    if result.get("bpm") and bpm_confidence >= 0.4:
        pairs.append((f"{int(round(result['bpm']))}bpm", bpm_confidence))

    key_confidence = result.get("key_confidence") or 0
    if result.get("tonic") is not None and key_confidence >= KEY_TAG_THRESHOLD:
        tonic_name = PITCH_CLASSES[result["tonic"]].replace("b", "flat").lower()
        name = f"{tonic_name}-{result['mode']}" if result["mode"] else tonic_name
        pairs.append((name, key_confidence))

    return pairs


def measured_tag_names(result):
    """Tags read directly from the container. Duration and channel count are
    not estimates, so these need no human ruling."""
    names = []

    duration = result.get("duration_seconds") or 0
    if duration < 2:
        names.append("one-shot")
    elif duration <= 30:
        names.append("loop")

    if result.get("channels") == 1:
        names.append("mono")

    return names


def derived_tag_names(result):
    """Every deterministic tag, regardless of status. Objective kind — each is
    verifiable from the audio, unlike a user's subjective tag."""
    return [name for name, _ in estimated_tag_names(result)] + measured_tag_names(result)