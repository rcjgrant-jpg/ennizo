from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    pass


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
