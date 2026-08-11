# social/forms.py
from pathlib import Path

from django import forms

from library.models import Folder, Sample

from .models import Comment, Post


class PostForm(forms.ModelForm):
    audio_file = forms.FileField(required=False)
    tags = forms.CharField(required=False)

    class Meta:
        model = Post
        fields = ["sample", "body"]
        widgets = {
            "body": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Say something about this sample...",
                "class": "w-full resize-none bg-transparent text-sm outline-none",
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["sample"].required = False
        self.fields["sample"].queryset = Sample.objects.in_library_of(user).filter(
            post__isnull=True
        )
        self.fields["sample"].empty_label = "Choose an existing sample…"

    def clean_audio_file(self):
        f = self.cleaned_data.get("audio_file")
        if not f:
            return None
        ext = Path(f.name).suffix.lower()
        if ext not in {".wav", ".mp3", ".aiff", ".flac"}:
            raise forms.ValidationError("Upload a WAV, MP3, AIFF or FLAC file.")
        if f.size > 100 * 1024 * 1024:
            raise forms.ValidationError("That file is too large (100MB maximum).")
        return f

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

    def clean(self):
        cleaned = super().clean()
        sample = cleaned.get("sample")
        upload = cleaned.get("audio_file")

        if not sample and not upload:
            raise forms.ValidationError(
                "Attach a sample — either choose one from your library or upload a file."
            )
        if sample and upload:
            raise forms.ValidationError(
                "Choose an existing sample or upload a new one, not both."
            )
        return cleaned

    def build_sample(self):
        """Create and return a Sample from the uploaded file. Caller must be in a transaction."""
        upload = self.cleaned_data["audio_file"]
        folder, _ = Folder.objects.get_or_create(
            library=self.user.library, name="Unsorted"
        )
        sample = Sample(
            folder=folder,
            title=Path(upload.name).stem,
            audio_file=upload,
            is_public=True,
        )
        sample.save()
        return sample


class CommentForm(forms.ModelForm):
    parent = forms.ModelChoiceField(
        queryset=Comment.objects.all(),
        required=False,
        widget=forms.HiddenInput,
    )

    class Meta:
        model = Comment
        fields = ["body"]
        widgets = {
            "body": forms.TextInput(attrs={
                "placeholder": "Add a comment...",
                "maxlength": 200,
                "class": (
                    "bg-muted border-border flex-1 rounded-md border "
                    "px-3 py-1.5 text-xs outline-none"
                ),
            }),
        }