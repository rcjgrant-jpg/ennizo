"""
Bridge between Django's storage abstraction and libraries that need a real
file on disk.

librosa, soundfile and Essentia all open audio by filesystem path. Local
FileSystemStorage can hand one over directly (``FieldFile.path``); a bucket
backend such as S3 cannot — there is no path, only a stream — and raises
``NotImplementedError``. ``local_copy`` hides that difference: it yields a
path in both cases, downloading to a temporary file only when it has to,
and cleans the temporary file up afterwards.

Usage::

    with local_copy(sample.audio_file) as path:
        y, sr = librosa.load(path)
"""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def local_copy(fieldfile):
    """Yield a ``Path`` to the file's bytes, whatever storage backs it."""
    try:
        path = Path(fieldfile.path)
    except NotImplementedError:
        path = None

    if path is not None:
        # Local storage: the file is already on disk, nothing to copy.
        yield path
        return

    # Remote storage: stream the object down into a temp file. Keep the
    # original extension so format sniffing (soundfile, ffmpeg) still works.
    suffix = Path(fieldfile.name).suffix
    fd, tmp_name = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            fieldfile.open("rb")
            try:
                for chunk in fieldfile.chunks():
                    out.write(chunk)
            finally:
                fieldfile.close()
        yield Path(tmp_name)
    finally:
        try:
            os.remove(tmp_name)
        except FileNotFoundError:
            pass
