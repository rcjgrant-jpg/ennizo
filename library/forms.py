# library/forms.py
from pathlib import Path

from django import forms

from .models import AUDIO_EXTENSIONS, Folder, Sample

ALLOWED_SUFFIXES = {f".{ext}" for ext in AUDIO_EXTENSIONS}


class SampleUploadForm(forms.ModelForm):
    tags = forms.CharField(
        required=False,
        help_text="Comma-separated, e.g. drums, breakbeat, lo-fi",
        widget=forms.TextInput(attrs={"placeholder": "drums, breakbeat, lo-fi"}),
    )
    folder = forms.ModelChoiceField(
        queryset=Folder.objects.none(),
        required=True,
        empty_label=None,
    )

    class Meta:
        model = Sample
        fields = ["title", "audio_file", "note", "is_public", "origin", "licence"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].required = False

        # E5: both declarations are required and neither is pre-selected —
        # the model default (UNKNOWN) exists for rows that predate the field,
        # not as something a form should silently submit.
        self.fields["origin"].required = True
        self.fields["origin"].initial = ""
        self.fields["origin"].choices = [("", "Choose…")] + list(Sample.Origin.choices)
        self.fields["licence"].required = True
        self.fields["licence"].initial = ""
        self.fields["licence"].choices = [("", "Choose…")] + list(Sample.Licence.choices)
        self.fields["folder"].queryset = Folder.objects.filter(
            library__user=user
        ).order_by("name")

        unsorted = self.fields["folder"].queryset.filter(name="Unsorted").first()
        if unsorted and not self.is_bound:
            self.fields["folder"].initial = unsorted.pk

    def clean_audio_file(self):
        f = self.cleaned_data["audio_file"]
        ext = Path(f.name).suffix.lower()
        if ext not in ALLOWED_SUFFIXES:
            raise forms.ValidationError("Upload a WAV, MP3, AIF or FLAC file.")
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


class FolderForm(forms.ModelForm):
    class Meta:
        model = Folder
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "Folder name",
                "class": "bg-muted border-border w-full rounded-md border px-3 py-2 text-sm",
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Give the folder a name.")
        exists = Folder.objects.filter(
            library__user=self.user, name__iexact=name
        ).exists()
        if exists:
            raise forms.ValidationError("You already have a folder with that name.")
        return name