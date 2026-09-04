import uuid
from pathlib import Path


def variant_upload_path(instance, filename):
    ext = Path(filename).suffix.lower() or ".wav"
    owner_id = instance.sample.folder.library.user_id
    return f"variants/{owner_id}/{uuid.uuid4().hex}{ext}"







