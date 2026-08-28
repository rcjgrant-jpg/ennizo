from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

INPUT_CLASSES = (
    "bg-muted border-border w-full rounded-md border px-3 py-2 text-sm outline-none "
    "focus:border-primary/60 transition-colors"
)


class RegisterForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")
        widgets = {
            "username": forms.TextInput(attrs={
                "class": INPUT_CLASSES, "placeholder": "your_producer_name",
                "autofocus": True, "autocomplete": "username",
            }),
            "email": forms.EmailInput(attrs={
                "class": INPUT_CLASSES, "placeholder": "you@example.com",
                "autocomplete": "email",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update({
            "class": INPUT_CLASSES, "placeholder": "Password",
            "autocomplete": "new-password", "id": "id_password1",
        })
        self.fields["password2"].widget.attrs.update({
            "class": INPUT_CLASSES, "placeholder": "Repeat password",
            "autocomplete": "new-password",
        })


class ProfileForm(forms.ModelForm):
    """Shared by first-time setup (post-registration) and later editing.

    One form, one view, one template: the only difference between the two
    moments is the heading, which the template resolves from a query flag.
    """

    class Meta:
        model = get_user_model()
        fields = ["avatar", "first_name", "last_name", "bio"]
        widgets = {
            "first_name": forms.TextInput(attrs={
                "class": INPUT_CLASSES, "placeholder": "First name",
            }),
            "last_name": forms.TextInput(attrs={
                "class": INPUT_CLASSES, "placeholder": "Last name",
            }),
            "bio": forms.Textarea(attrs={
                "class": INPUT_CLASSES, "rows": 4,
                "placeholder": "Tell people what you make. Links are clickable.",
            }),
        }

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar and avatar.size > 5 * 1024 * 1024:
            raise forms.ValidationError("That image is too large (5MB maximum).")
        return avatar