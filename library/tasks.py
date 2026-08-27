from celery import shared_task
from .models import Sample

import logging

logger = logging.getLogger(__name__)


@shared_task
def reap_abandoned_samples():
    count = Sample.objects.reap_uncommitted()
    if count:
        logger.info("reaped %d abandoned samples", count)
    return count