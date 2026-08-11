# library/forms.py
# library/forms.py
from pathlib import Path

from django import forms

from .models import Sample, Tag, SampleTag


class SampleUploadForm(forms.ModelForm):
    tags = forms.CharField(
        required=False,
        help_text="Comma-separated, e.g. drums, breakbeat, lo-fi",
        widget=forms.TextInput(attrs={"placeholder": "drums, breakbeat, lo-fi"}),
    )

    class Meta:
        model = Sample
        fields = ["title", "audio_file", "note", "is_public"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].required = False

    def clean_audio_file(self):
        f = self.cleaned_data["audio_file"]
        ext = Path(f.name).suffix.lower()
        if ext not in {".wav", ".mp3", ".aiff", ".flac"}:
            raise forms.ValidationError("Upload a WAV, MP3, AIFF or FLAC file.")
        if f.size > 100 * 1024 * 1024:
            raise forms.ValidationError("That file is too large (100MB maximum).")
        return f

    def clean_title(self):
        title = self.cleaned_data.get("title", "").strip()
        if title:
            return title
        uploaded = self.files.get("audio_file")
        return Path(uploaded.name).stem if uploaded else ""

    def clean_tags(self):
        raw = self.cleaned_data.get("tags", "")
        names = []
        for part in raw.split(","):
            name = part.strip().lower()
            if name and name not in names:
                names.append(name)
        if len(names) > 10:
            raise forms.ValidationError("Ten tags maximum.")
        return names