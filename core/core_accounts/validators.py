import re

from django.core.exceptions import ValidationError


class StrongPasswordValidator:
    """At least 8 characters with an uppercase letter, a lowercase letter,
    a number and a special symbol. No spaces."""

    RULES = [
        (r'[A-Z]', "an uppercase letter"),
        (r'[a-z]', "a lowercase letter"),
        (r'\d', "a number"),
        (r'[^A-Za-z0-9\s]', "a special symbol (e.g. ! @ # $ -)"),
    ]

    def validate(self, password, user=None):
        if re.search(r'\s', password):
            raise ValidationError("Password can't contain spaces.", code='password_has_spaces')
        missing = [label for pattern, label in self.RULES if not re.search(pattern, password)]
        if len(password) < 8:
            missing.insert(0, "at least 8 characters")
        if missing:
            raise ValidationError(
                "Password needs " + ", ".join(missing[:-1]) + (" and " if len(missing) > 1 else "") + missing[-1] + ".",
                code='password_too_weak',
            )

    def get_help_text(self):
        return ("Your password must have at least 8 characters, with an uppercase letter, "
                "a lowercase letter, a number and a special symbol, and no spaces.")