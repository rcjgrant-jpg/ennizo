from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    # Profile fields live directly on the user rather than in a separate
    # Profile model: the project already owns a custom user model, so a
    # one-to-one indirection would buy nothing but an extra join and a
    # signal to keep the rows in sync. first_name / last_name are inherited
    # from AbstractUser and reused as-is.
    bio = models.TextField(blank=True, max_length=500)
    avatar = models.ImageField(upload_to="avatars/", blank=True)

    @property
    def initials(self):
        """Two-letter fallback shown wherever no avatar has been uploaded."""
        if self.first_name and self.last_name:
            return (self.first_name[0] + self.last_name[0]).upper()
        return self.username[:2].upper()


class Library(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="library",
    )

    class Meta:
        verbose_name_plural = "libraries"

    def __str__(self):
        return f"{self.user.username}'s library"

