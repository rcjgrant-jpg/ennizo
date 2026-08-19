import numpy as np

PEAK_BUCKETS = 2000

def compute_peaks(y, buckets=PEAK_BUCKETS):
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