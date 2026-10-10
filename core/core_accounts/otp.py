"""
One-time codes by email.

    send_code(purpose, email)         -> emails a new 6-digit code
    verify_code(purpose, email, code) -> True, or raises OTPError with a message for the user

Rules: a code lasts 5 minutes, only the newest code works, 5 wrong tries
and it's dead, a new code at most every 60 s and 5 per hour per email.
Codes are stored as a keyed hash, never as plain text.

Emails go out through settings.MAILERS (EMAIL_HOST ... in .env; with no
EMAIL_HOST they're printed in the runserver terminal instead).
"""
import math
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import OTPCode

Purpose = OTPCode.Purpose

CODE_LENGTH = 6
CODE_LIFETIME = timedelta(minutes=5)
RESEND_AFTER = timedelta(seconds=60)
MAX_ATTEMPTS = 5
MAX_PER_HOUR = 5


class OTPError(Exception):
    """Something the user should read (wrong code, wait before resending ...)."""


# ------------------------------------------------------------------ helpers

def normalize(email):
    return (email or '').strip().lower()


def _hash(purpose, email, code):
    # Keyed with SECRET_KEY: a leaked database alone can't be used to guess codes
    return salted_hmac('lookapt.otp', f'{purpose}:{email}:{code}').hexdigest()


def _latest(purpose, email):
    return OTPCode.objects.filter(purpose=purpose, target=email).order_by('-created_at', '-pk').first()


def mask(email):
    """be***@gmail.com (for "we sent a code to ...")."""
    name, _, domain = email.partition('@')
    return f"{name[:2]}{'*' * max(len(name) - 2, 3)}@{domain}"


def seconds_until_resend(purpose, email):
    latest = _latest(purpose, normalize(email))
    if latest is None:
        return 0
    wait = (latest.created_at + RESEND_AFTER - timezone.now()).total_seconds()
    return max(0, math.ceil(wait))


def seconds_until_expiry(purpose, email):
    latest = _latest(purpose, normalize(email))
    if latest is None or latest.used_at:
        return 0
    return max(0, math.ceil((latest.expires_at - timezone.now()).total_seconds()))


# ------------------------------------------------------------------ sending

def send_code(purpose, email, name=''):
    """Make a new code and email it (name = first name for the greeting).
    Raises OTPError if it's too soon or sending failed."""
    email = normalize(email)
    now = timezone.now()
    OTPCode.objects.filter(created_at__lt=now - timedelta(days=1)).delete()   # tidy up old codes

    wait = seconds_until_resend(purpose, email)
    if wait:
        raise OTPError(f"Please wait {wait} seconds before asking for a new code.")
    recent = OTPCode.objects.filter(purpose=purpose, target=email, created_at__gte=now - timedelta(hours=1))
    if recent.count() >= MAX_PER_HOUR:
        raise OTPError("Too many codes requested. Please try again in an hour.")

    code = f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"
    otp = OTPCode.objects.create(
        purpose=purpose, channel=OTPCode.Channel.EMAIL, target=email,
        code_hash=_hash(purpose, email, code), expires_at=now + CODE_LIFETIME,
    )
    try:
        deliver(email, code, purpose, name)
    except Exception:
        otp.delete()        # a code nobody received shouldn't block a resend
        raise OTPError("We couldn't send the code to your email. Please try again.")
    return otp


def deliver(email, code, purpose=Purpose.SIGNUP, name=''):
    minutes = int(CODE_LIFETIME.total_seconds() // 60)
    greeting = f"Hello, {name}!" if name else "Hello!"
    if purpose == Purpose.SIGNUP:
        intro = "Welcome to LookApt! To finish setting up your account, enter this verification code:"
    else:
        intro = "Use this code to reset your LookApt password:"
    text = (
        f"{greeting}\n\n"
        f"{intro} {code}\n"
        f"It expires in {minutes} minutes. Don't share it with anyone.\n"
        f"If you didn't ask for this, you can ignore this email."
    )
    send_mail("Your LookApt verification code", text, settings.DEFAULT_FROM_EMAIL, [email])


# ------------------------------------------------------------------ checking

def verify_code(purpose, email, code):
    """True if the code is right (it's then used up). Otherwise raises OTPError."""
    email = normalize(email)
    code = ''.join(ch for ch in (code or '') if ch.isdigit())
    otp = _latest(purpose, email)

    if otp is None or otp.used_at:
        raise OTPError("Please request a new code.")
    if otp.expires_at <= timezone.now():
        raise OTPError("This code has expired. Please request a new one.")
    if otp.attempts >= MAX_ATTEMPTS:
        raise OTPError("Too many wrong tries. Please request a new code.")
    if len(code) != CODE_LENGTH or not constant_time_compare(otp.code_hash, _hash(purpose, email, code)):
        OTPCode.objects.filter(pk=otp.pk).update(attempts=F('attempts') + 1)
        left = MAX_ATTEMPTS - otp.attempts - 1
        if left <= 0:
            raise OTPError("Too many wrong tries. Please request a new code.")
        raise OTPError(f"That code is incorrect. {left} {'try' if left == 1 else 'tries'} left.")

    used = OTPCode.objects.filter(pk=otp.pk, used_at__isnull=True).update(used_at=timezone.now())
    if not used:                       # someone used it a moment ago
        raise OTPError("Please request a new code.")
    return True