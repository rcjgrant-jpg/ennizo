from django import forms

from library.models import Sample

from .models import Post


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ["sample", "body"]
        widgets = {
            "body": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Say something about this sample...",
                "class": "bg-transparent w-full resize-none text-sm outline-none",
            }),
            "sample": forms.Select(attrs={
                "class": "bg-muted rounded-md px-2 py-1 text-xs",
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sample"].queryset = Sample.objects.in_library_of(user).filter(
            post__isnull=True
        )