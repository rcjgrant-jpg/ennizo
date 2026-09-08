import numpy as np
import librosa

from analysis.models import MIN_TEMPO_DURATION

SILENCE_EDGE_SECONDS = 0.25   # leading/trailing silence longer than this is flagged


def quality_flags(y, sr, facts):
    """Boolean quality faults shown on the analysis page (U3.9).

    Every value is a builtin bool: NumPy's np.bool_ is not JSON-serialisable
    and this dict is stored in a JSONField.
    """
    if not y.size:
        return {}

    _, (start, end) = librosa.effects.trim(y, top_db=40)

    return {
        "clipping": bool(np.sum(np.abs(y) >= 0.99) > y.size * 0.0001),
        "very_quiet": bool(np.max(np.abs(y)) < 0.1),
        "dc_offset": bool(abs(np.mean(y)) > 0.01),
        "low_sample_rate": bool(facts["sample_rate"] < 44100),
        "too_short_for_tempo": bool(facts["duration_seconds"] < MIN_TEMPO_DURATION),
        "leading_silence": bool(start / sr > SILENCE_EDGE_SECONDS),
        "trailing_silence": bool((y.size - end) / sr > SILENCE_EDGE_SECONDS),
    }