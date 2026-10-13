"""
One-time codes by email.

    code = OneTimeCode(Purpose.SIGNUP, email)
    code.send(name)     -> emails a new 6-digit code
    code.verify(entered) -> True, or raises OTPError with a message for the user

Rules: a code lasts 5 minutes, only the newest code works, 5 wrong tries
and it's dead, a new code at most every 60 s and 5 per hour per email.
Codes are stored as a keyed hash, never as plain text.

Emails go out through settings.MAILERS (EMAIL_HOST ... in .env; with no
EMAIL_HOST they're printed in the runserver terminal instead).
"""
import math
import secrets
from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .emails import LookAptEmail
from .models import OTPCode

Purpose = OTPCode.Purpose


class OTPError(Exception):
    """Something the user should read (wrong code, wait before resending ...)."""


class OneTimeCode:
    """The codes of one email for one purpose (sign-up or reset password)."""

    LENGTH = 6
    LIFETIME = timedelta(minutes=5)
    RESEND_AFTER = timedelta(seconds=60)
    MAX_ATTEMPTS = 5
    MAX_PER_HOUR = 5

    def __init__(self, purpose, email):
        self.purpose = purpose
        self.email = (email or '').strip().lower()

    # ------------------------------------------------------------------ helpers

    def _hash(self, code):
        # Keyed with SECRET_KEY: a leaked database alone can't be used to guess codes
        return salted_hmac('lookapt.otp', f'{self.purpose}:{self.email}:{code}').hexdigest()

    def _latest(self):
        return OTPCode.objects.filter(purpose=self.purpose, target=self.email).order_by('-created_at', '-pk').first()

    @property
    def masked_target(self):
        """be***@gmail.com (for "we sent a code to ...")."""
        name, _, domain = self.email.partition('@')
        return f"{name[:2]}{'*' * max(len(name) - 2, 3)}@{domain}"

    @property
    def seconds_until_resend(self):
        latest = self._latest()
        if latest is None:
            return 0
        wait = (latest.created_at + self.RESEND_AFTER - timezone.now()).total_seconds()
        return max(0, math.ceil(wait))

    @property
    def seconds_until_expiry(self):
        latest = self._latest()
        if latest is None or latest.used_at:
            return 0
        return max(0, math.ceil((latest.expires_at - timezone.now()).total_seconds()))

    # ------------------------------------------------------------------ sending

    def send(self, name=''):
        """Make a new code and email it (name = first name for the greeting).
        Raises OTPError if it's too soon or sending failed."""
        now = timezone.now()
        OTPCode.objects.filter(created_at__lt=now - timedelta(days=1)).delete()   # tidy up old codes

        wait = self.seconds_until_resend
        if wait:
            raise OTPError(f"Please wait {wait} seconds before asking for a new code.")
        recent = OTPCode.objects.filter(purpose=self.purpose, target=self.email, created_at__gte=now - timedelta(hours=1))
        if recent.count() >= self.MAX_PER_HOUR:
            raise OTPError("Too many codes requested. Please try again in an hour.")

        code = f"{secrets.randbelow(10 ** self.LENGTH):0{self.LENGTH}d}"
        otp = OTPCode.objects.create(
            purpose=self.purpose, channel=OTPCode.Channel.EMAIL, target=self.email,
            code_hash=self._hash(code), expires_at=now + self.LIFETIME,
        )
        try:
            CodeEmail(self.email, code, self.purpose, name).send()
        except Exception:
            otp.delete()        # a code nobody received shouldn't block a resend
            raise OTPError("We couldn't send the code to your email. Please try again.")
        return otp

    # ------------------------------------------------------------------ checking

    def verify(self, code):
        """True if the code is right (it's then used up). Otherwise raises OTPError."""
        code = ''.join(ch for ch in (code or '') if ch.isdigit())
        otp = self._latest()

        if otp is None or otp.used_at:
            raise OTPError("Please request a new code.")
        if otp.expires_at <= timezone.now():
            raise OTPError("This code has expired. Please request a new one.")
        if otp.attempts >= self.MAX_ATTEMPTS:
            raise OTPError("Too many wrong tries. Please request a new code.")
        if len(code) != self.LENGTH or not constant_time_compare(otp.code_hash, self._hash(code)):
            OTPCode.objects.filter(pk=otp.pk).update(attempts=F('attempts') + 1)
            left = self.MAX_ATTEMPTS - otp.attempts - 1
            if left <= 0:
                raise OTPError("Too many wrong tries. Please request a new code.")
            raise OTPError(f"That code is incorrect. {left} {'try' if left == 1 else 'tries'} left.")

        used = OTPCode.objects.filter(pk=otp.pk, used_at__isnull=True).update(used_at=timezone.now())
        if not used:                       # someone used it a moment ago
            raise OTPError("Please request a new code.")
        return True


class CodeEmail(LookAptEmail):
    """The email with the 6-digit code (inherits the logo and layout from LookAptEmail)."""

    template_name = 'core_accounts/emails/otp_code.html'

    def __init__(self, email, code, purpose=Purpose.SIGNUP, name=''):
        super().__init__(email, "Your LookApt verification code")
        self.code = code
        self.minutes = int(OneTimeCode.LIFETIME.total_seconds() // 60)
        self.greeting = f"Hello, {name}!" if name else "Hello!"
        if purpose == Purpose.SIGNUP:
            self.intro = "Welcome to LookApt! To finish setting up your account, enter this verification code:"
        else:
            self.intro = "Use this code to reset your LookApt password:"

    def text(self):
        return (
            f"{self.greeting}\n\n"
            f"{self.intro} {self.code}\n"
            f"It expires in {self.minutes} minutes. Don't share it with anyone. If you didn't ask for this, you can ignore this email."
            f"\n\nBest,\nLookApt"
        )

    def html_context(self):
        return {'greeting': self.greeting, 'intro': self.intro, 'code': self.code, 'minutes': self.minutes}
