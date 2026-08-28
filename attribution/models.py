from django.conf import settings
from django.db import models


class DownloadRecord(models.Model):
    """One row per (user, sample) pair, however many times the file is fetched.

    Uniqueness on (downloader, sample) means the download count reads as
    "how many people have this", not "how many times was the button pressed".
    """

    downloader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="downloads",
    )
    sample = models.ForeignKey(
        "library.Sample",
        on_delete=models.CASCADE,
        related_name="downloads",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["downloader", "sample"],
                name="unique_download_per_user_sample",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.downloader} downloaded {self.sample_id}"


class CreditRecord(models.Model):
    """A downloader crediting a released track back to the sample it used.

    Keyed to (creditor, sample) rather than to a DownloadRecord: the credit
    is about the sample, not the download event, and a producer may use one
    sample in several tracks — so no uniqueness constraint here.

    One platform + one URL per credit, matching the UI: the dropdown offers
    a choice of platform, not three parallel link fields. A second platform
    for the same track is simply a second credit.
    """

    class Platform(models.TextChoices):
        SOUNDCLOUD = "soundcloud", "SoundCloud"
        SPOTIFY = "spotify", "Spotify"
        APPLEMUSIC = "applemusic", "Apple Music"

    creditor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="credits_given",
    )
    sample = models.ForeignKey(
        "library.Sample",
        on_delete=models.CASCADE,
        related_name="credits",
    )
    platform = models.CharField(max_length=20, choices=Platform.choices)
    track_title = models.CharField(max_length=200)
    track_url = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.creditor} credited {self.sample_id} in “{self.track_title}”"