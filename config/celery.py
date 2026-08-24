import os

from celery import Celery

import ffmpeg
import pyloudnorm
import noisereduce
from scipy import signal
import numpy as np

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("ennizo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


# @app.task

# def apply_edit.delay(*args, **kwargs):
#     return

# def apply_trim(audio, sr, start, end):
#     return

# def apply_eq(audio, sr, nodes):
#     return

# def apply_loud_norm(audio, sr):
#     return

# def apply_denosie(audio, sr):
#     return

    

@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")