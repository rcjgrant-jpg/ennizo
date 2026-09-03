from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from .models import Library, User


DEFAULT_FOLDER_NAME = "Unsorted"


# --- Library provisioning ------------------------------------------------------

@receiver(post_save, sender=User)
def create_library_for_new_user(sender, instance, created, **kwargs):
    """Every account owns exactly one Library, and every Library starts with
    an "Unsorted" folder so the first upload has somewhere to land. Done as
    a signal rather than in the register view so that users created any
    other way (admin, createsuperuser, tests) are provisioned identically."""
    if not created:
        return
    # Imported here: library.models refers to accounts.Library, so a
    # module-level import in the other direction would be circular.
    from library.models import Folder

    library, _ = Library.objects.get_or_create(user=instance)
    Folder.objects.get_or_create(library=library, name=DEFAULT_FOLDER_NAME)


# --- Avatar file lifecycle -------------------------------------------------------

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