# social/forms.py
from pathlib import Path

from django import forms
from django.db.models import Q

from library.forms import ALLOWED_SUFFIXES
from library.models import Folder, Sample

from .models import Comment, Post

class DraftForm(forms.Form):
    """Phase one: attach a sample. File validation only."""
    audio_file = forms.FileField(required=False)
    sample = forms.ModelChoiceField(queryset=Sample.objects.none(), required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["sample"].queryset = Sample.objects.in_library_of(user).filter(
            Q(post__isnull=True) | Q(post__is_published=False)
        )

    def clean_audio_file(self):
        f = self.cleaned_data.get("audio_file")
        if not f:
            return None
        if Path(f.name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise forms.ValidationError("Upload a WAV, MP3, AIF or FLAC file.")
        if f.size > 100 * 1024 * 1024:
            raise forms.ValidationError("That file is too large (100MB maximum).")
        return f

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("sample") and not cleaned.get("audio_file"):
            raise forms.ValidationError(
                "Attach a sample — either choose one from your library or upload a file."
            )
        if cleaned.get("sample") and cleaned.get("audio_file"):
            raise forms.ValidationError(
                "Choose an existing sample or upload a new one, not both."
            )
        return cleaned

    def build_sample(self):
        upload = self.cleaned_data["audio_file"]
        folder, _ = Folder.objects.get_or_create(
            library=self.user.library, name="Unsorted"
        )
        sample = Sample(
            folder=folder,
            title=Path(upload.name).stem,
            audio_file=upload,
            is_public=True,
            is_committed=False,
        )
        sample.save()
        return sample


class PublishForm(forms.ModelForm):
    """Phase two: the caption and tags, written onto an existing draft.

    Also carries the sample's provenance declaration (E5). The fields belong
    to Sample, not Post, so they are plain form fields here and the view
    writes them onto post.sample; a ModelForm over two models would be more
    machinery than two selects deserve.
    """
    _SELECT_CLASS = (
        "bg-muted border-border w-full rounded-md border px-3 py-2 text-xs outline-none"
    )

    origin = forms.ChoiceField(                                     # U5.1
        choices=[("", "Where did this sample come from?")] + list(Sample.Origin.choices),
        required=True,
        widget=forms.Select(attrs={"class": _SELECT_CLASS}),
        error_messages={"required": "Say where the sample came from before posting."},
    )
    licence = forms.ChoiceField(                                    # U5.2
        choices=[("", "How may others use it?")] + list(Sample.Licence.choices),
        required=True,
        widget=forms.Select(attrs={"class": _SELECT_CLASS}),
        error_messages={"required": "Choose a licence before posting."},
    )

    @classmethod
    def for_sample(cls, sample):
        """Unbound form pre-filled from a sample's existing declaration, so a
        library sample attached to a new post shows what was declared at
        upload. UNKNOWN is left blank: it must be replaced, not confirmed."""
        initial = {"licence": sample.licence}
        if sample.origin != Sample.Origin.UNKNOWN:
            initial["origin"] = sample.origin
        return cls(initial=initial)

    def clean_origin(self):
        # U5.4: the gate. Unknown-origin material may sit in a library but
        # is refused at publication, which is the point at which it would
        # be offered to other people.
        origin = self.cleaned_data["origin"]
        if origin == Sample.Origin.UNKNOWN:
            raise forms.ValidationError(
                "Samples of unknown or third-party origin can't be posted. "
                "You can still keep this one in your library."
            )
        return origin

    class Meta:
        model = Post
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Say something about this sample...",
                "class": "w-full resize-none bg-transparent text-sm outline-none",
            }),
        }


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