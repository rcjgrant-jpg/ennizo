import re

from django.core.exceptions import ValidationError


class ComplexityValidator:
    """At least two digits and one special character.

    Mirrors the live checklist on the registration page exactly: the ticks
    are client-side convenience, this is the enforcement. If either changes,
    change both.
    """

    def validate(self, password, user=None):
        if len(re.findall(r"\d", password)) < 2:
            raise ValidationError(
                "Your password must contain at least 2 numbers.",
                code="password_too_few_digits",
            )
        if not re.search(r"[^A-Za-z0-9]", password):
            raise ValidationError(
                "Your password must contain at least 1 special character.",
                code="password_no_special",
            )

    def get_help_text(self):
        return "Your password must contain at least 2 numbers and 1 special character."