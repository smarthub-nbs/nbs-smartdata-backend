import re

from django.core.exceptions import ValidationError


class StrongPasswordValidator:
    uppercase_pattern = re.compile(r"[A-Z]")
    lowercase_pattern = re.compile(r"[a-z]")
    digit_pattern = re.compile(r"\d")
    special_pattern = re.compile(r"[^A-Za-z0-9]")
    whitespace_pattern = re.compile(r"\s")

    def validate(self, password, user=None):
        errors = []

        if not self.uppercase_pattern.search(password):
            errors.append("Password must contain at least one uppercase letter.")
        if not self.lowercase_pattern.search(password):
            errors.append("Password must contain at least one lowercase letter.")
        if not self.digit_pattern.search(password):
            errors.append("Password must contain at least one number.")
        if not self.special_pattern.search(password):
            errors.append("Password must contain at least one special character.")
        if self.whitespace_pattern.search(password):
            errors.append("Password must not contain whitespace.")

        if errors:
            raise ValidationError(errors, code="password_not_strong_enough")

    def get_help_text(self):
        return (
            "Your password must be at least 8 characters long and contain at least "
            "one uppercase letter, one lowercase letter, one number, and one "
            "special character. Whitespace is not allowed."
        )
