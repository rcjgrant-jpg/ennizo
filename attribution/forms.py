from urllib.parse import urlparse

from django import forms

from .models import CreditRecord

INPUT_CLASSES = (
    "bg-background border-border w-full rounded-md border px-3 py-2 text-sm outline-none"
)

# Exact-host allowlists per platform. Deliberately strict: an exact match
# against known hosts can't be fooled the way a suffix check can (a naive
# endswith("spotify.com") would accept evil-spotify.com). This verifies the
# link's FORMAT — that it points at the platform the user selected — not
# that the track behind it exists; confirming that would mean fetching the
# URL server-side on every submission.
PLATFORM_HOSTS = {
    CreditRecord.Platform.SOUNDCLOUD: {
        "soundcloud.com", "m.soundcloud.com", "on.soundcloud.com",
    },
    CreditRecord.Platform.SPOTIFY: {
        "open.spotify.com", "spotify.link",
    },
    CreditRecord.Platform.APPLEMUSIC: {
        "music.apple.com", "itunes.apple.com",
    },
}


class CreditForm(forms.ModelForm):
    class Meta:
        model = CreditRecord
        fields = ["platform", "track_title", "track_url"]
        widgets = {
            "platform": forms.Select(attrs={"class": INPUT_CLASSES}),
            "track_title": forms.TextInput(attrs={
                "class": INPUT_CLASSES, "placeholder": "Track title",
            }),
            "track_url": forms.URLInput(attrs={
                "class": INPUT_CLASSES, "placeholder": "https://…",
            }),
        }

    def clean(self):
        cleaned = super().clean()
        platform = cleaned.get("platform")
        url = cleaned.get("track_url")

        if platform and url:
            host = urlparse(url).netloc.lower().rsplit("@", 1)[-1].split(":")[0]
            if host.startswith("www."):
                host = host[4:]

            if host not in PLATFORM_HOSTS.get(platform, set()):
                label = CreditRecord.Platform(platform).label
                # Attached to the field (not a non-field error) so the
                # dropdown's existing per-field error rendering shows it.
                self.add_error(
                    "track_url",
                    f"That doesn't look like a {label} link. "
                    f"Paste the track's share URL from {label}.",
                )

        return cleaned
