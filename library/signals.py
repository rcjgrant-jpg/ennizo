from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Comment, Notification

@receiver(post_save, sender=Comment)
def notify_on_reply(sender, instance, created, **kwargs):
    if created and instance.parent_id:
        parent_author = instance.parent.author
        if parent_author != instance.author:   # don't notify yourself
            Notification.objects.create(
                recipient=parent_author,
                actor=instance.author,
                verb="replied",
                comment=instance,
            )