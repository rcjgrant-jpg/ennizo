import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Sample

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Sample)
def delete_sample_file(sender, instance, **kwargs):
    """Remove the audio file from storage when its Sample row is deleted."""
    
    if instance.audio_file:
        instance.audio_file.delete(save=False)