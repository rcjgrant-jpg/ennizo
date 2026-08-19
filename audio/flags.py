import numpy as np
import librosa

def quality_flags(y, sr, facts, duration):
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