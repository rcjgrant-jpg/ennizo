from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from .models import User
 

 
_STASH_ATTR = "_replaced_avatar_name"
 
 
def _delete_file(storage, name):
    """Delete `name` from `storage` if present. Never raises."""
    if not name:
        return
    try:
        if storage.exists(name):
            storage.delete(name)
    except Exception:
        
        pass
 
 
@receiver(pre_save, sender=User)
def stash_replaced_avatar(sender, instance, **kwargs):
    """Record the outgoing avatar name if it is about to be replaced or cleared."""
    if not instance.pk:
        return
    try:
        old_name = (
            sender.objects.filter(pk=instance.pk)
            .values_list("avatar", flat=True)
            .first()
        )
    except sender.DoesNotExist:
        return
 
    new_name = instance.avatar.name if instance.avatar else ""
    if old_name and old_name != new_name:
        setattr(instance, _STASH_ATTR, old_name)
 
 
@receiver(post_save, sender=User)
def delete_replaced_avatar(sender, instance, **kwargs):
    """After a successful commit, remove the file stashed by pre_save."""
    old_name = getattr(instance, _STASH_ATTR, None)
    if not old_name:
        return
    delattr(instance, _STASH_ATTR)
    storage = instance.avatar.storage
    transaction.on_commit(lambda: _delete_file(storage, old_name))
 
 
@receiver(post_delete, sender=User)
def delete_avatar_on_row_delete(sender, instance, **kwargs):
    """Row deletion removes the current avatar file."""
    if instance.avatar:
        storage = instance.avatar.storage
        name = instance.avatar.name
        transaction.on_commit(lambda: _delete_file(storage, name))