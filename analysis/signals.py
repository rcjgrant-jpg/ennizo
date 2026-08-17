from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from library.models import Sample
from .models import DerivedMetadata
from .tasks import analyse_sample


@receiver(post_save, sender=Sample)
def enqueue_analysis(sender, instance, created, **kwargs):
    if not created:
        return

    DerivedMetadata.objects.get_or_create(sample=instance)

    # on_commit, not immediately: the Celery worker is a separate process and
    # will raise DoesNotExist if it picks the job up before this transaction
    # has committed. This is the single most common cause of "the task ran
    # but the sample didn't exist".
    transaction.on_commit(lambda: analyse_sample.delay(instance.pk))