from django.db import models


class OTPCode(models.Model):
    """A one-time code sent by SMS or email (sign-up now, forgot password later).
    The code itself is never stored, only a keyed hash of it (core_accounts/otp.py)."""

    class Purpose(models.TextChoices):
        SIGNUP = 'signup', 'Sign up'
        RESET = 'reset', 'Reset password'

    class Channel(models.TextChoices):
        SMS = 'sms', 'SMS'
        EMAIL = 'email', 'Email'

    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    target = models.CharField(max_length=254)            # 09XXXXXXXXX or a lower-case email
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['purpose', 'target', '-created_at'])]

    def __str__(self):
        return f"{self.get_purpose_display()} code for {self.target}"