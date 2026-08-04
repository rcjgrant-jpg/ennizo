from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from library.models import Folder

from .models import Library


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_library_for_new_user(sender, instance, created, **kwargs):
    """Every user gets a Library and a default Folder on creation."""
    if not created:
        return
    library, _ = Library.objects.get_or_create(user=instance)
    Folder.objects.get_or_create(library=library, name="Unsorted")
