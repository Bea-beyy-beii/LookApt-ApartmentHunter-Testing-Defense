"""
One-time codes by SMS or email.

    send_code(purpose, channel, target)  -> sends a new 6-digit code
    verify_code(purpose, target, code)   -> True, or raises OTPError with a message for the user

Rules: a code lasts 5 minutes, only the newest code works, 5 wrong tries
and it's dead, a new code at most every 60 s and 5 per hour per number /
email. Codes are stored as a keyed hash, never as plain text.

Where codes go is set in settings / .env:
    SMS:   OTP_SMS_PROVIDER = console (prints to the runserver terminal) | semaphore | twilio
    Email: EMAIL_BACKEND (console in development, SMTP in production)
"""
import math
import secrets
from datetime import timedelta

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import OTPCode

Purpose = OTPCode.Purpose
Channel = OTPCode.Channel

CODE_LENGTH = 6
CODE_LIFETIME = timedelta(minutes=5)
RESEND_AFTER = timedelta(seconds=60)
MAX_ATTEMPTS = 5
MAX_PER_HOUR = 5

SEMAPHORE_URL = "https://api.semaphore.co/api/v4/messages"
TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class OTPError(Exception):
    """Something the user should read (wrong code, wait before resending ...)."""


# ------------------------------------------------------------------ helpers

def normalize(channel, target):
    target = (target or '').strip()
    return target.lower() if channel == Channel.EMAIL else target.replace(' ', '').replace('-', '')


def _hash(purpose, target, code):
    # Keyed with SECRET_KEY: a leaked database alone can't be used to guess codes
    return salted_hmac('lookapt.otp', f'{purpose}:{target}:{code}').hexdigest()


def _latest(purpose, target):
    return OTPCode.objects.filter(purpose=purpose, target=target).order_by('-created_at', '-pk').first()


def mask(channel, target):
    """0917 *** **67  /  be***@gmail.com (for "we sent a code to ...")."""
    if channel == Channel.EMAIL:
        name, _, domain = target.partition('@')
        return f"{name[:2]}{'*' * max(len(name) - 2, 3)}@{domain}"
    return f"{target[:4]} *** **{target[-2:]}" if len(target) == 11 else target


def seconds_until_resend(purpose, target):
    latest = _latest(purpose, target)
    if latest is None:
        return 0
    wait = (latest.created_at + RESEND_AFTER - timezone.now()).total_seconds()
    return max(0, math.ceil(wait))


def seconds_until_expiry(purpose, target):
    latest = _latest(purpose, target)
    if latest is None or latest.used_at:
        return 0
    return max(0, math.ceil((latest.expires_at - timezone.now()).total_seconds()))


# ------------------------------------------------------------------ sending

def send_code(purpose, channel, target):
    """Make a new code and send it. Raises OTPError if it's too soon or sending failed."""
    target = normalize(channel, target)
    now = timezone.now()
    OTPCode.objects.filter(created_at__lt=now - timedelta(days=1)).delete()   # tidy up old codes

    wait = seconds_until_resend(purpose, target)
    if wait:
        raise OTPError(f"Please wait {wait} seconds before asking for a new code.")
    recent = OTPCode.objects.filter(purpose=purpose, target=target, created_at__gte=now - timedelta(hours=1))
    if recent.count() >= MAX_PER_HOUR:
        raise OTPError("Too many codes requested. Please try again in an hour.")

    code = f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"
    otp = OTPCode.objects.create(
        purpose=purpose, channel=channel, target=target,
        code_hash=_hash(purpose, target, code), expires_at=now + CODE_LIFETIME,
    )
    try:
        deliver(channel, target, code)
    except Exception:
        otp.delete()        # a code nobody received shouldn't block a resend
        where = "email" if channel == Channel.EMAIL else "phone number"
        raise OTPError(f"We couldn't send the code to your {where}. Please try again.")
    return otp


def deliver(channel, target, code):
    minutes = int(CODE_LIFETIME.total_seconds() // 60)
    text = (f"Your LookApt code is {code}. It expires in {minutes} minutes. "
            f"Don't share it with anyone.")

    if channel == Channel.EMAIL:
        send_mail("Your LookApt verification code", text, settings.DEFAULT_FROM_EMAIL, [target])
        return

    provider = settings.OTP_SMS_PROVIDER
    if provider == 'semaphore':
        data = {'apikey': settings.SEMAPHORE_API_KEY, 'number': target, 'message': text}
        if settings.SEMAPHORE_SENDER_NAME:
            data['sendername'] = settings.SEMAPHORE_SENDER_NAME
        requests.post(SEMAPHORE_URL, data=data, timeout=10).raise_for_status()
    elif provider == 'twilio':
        sid = settings.TWILIO_ACCOUNT_SID
        requests.post(
            TWILIO_URL.format(sid=sid), auth=(sid, settings.TWILIO_AUTH_TOKEN), timeout=10,
            data={'To': '+63' + target[1:], 'From': settings.TWILIO_FROM_NUMBER, 'Body': text},
        ).raise_for_status()
    elif provider == 'console':
        # Development: the code shows in the runserver terminal instead of a real SMS
        print(f"[LookApt OTP] SMS to {target}: {text}", flush=True)
    else:
        raise ValueError(f"Unknown OTP_SMS_PROVIDER: {provider!r}")


# ------------------------------------------------------------------ checking

def verify_code(purpose, target, code, channel=Channel.SMS):
    """True if the code is right (it's then used up). Otherwise raises OTPError."""
    target = normalize(channel, target)
    code = ''.join(ch for ch in (code or '') if ch.isdigit())
    otp = _latest(purpose, target)

    if otp is None or otp.used_at:
        raise OTPError("Please request a new code.")
    if otp.expires_at <= timezone.now():
        raise OTPError("This code has expired. Please request a new one.")
    if otp.attempts >= MAX_ATTEMPTS:
        raise OTPError("Too many wrong tries. Please request a new code.")
    if len(code) != CODE_LENGTH or not constant_time_compare(otp.code_hash, _hash(purpose, target, code)):
        OTPCode.objects.filter(pk=otp.pk).update(attempts=F('attempts') + 1)
        left = MAX_ATTEMPTS - otp.attempts - 1
        if left <= 0:
            raise OTPError("Too many wrong tries. Please request a new code.")
        raise OTPError(f"That code is incorrect. {left} {'try' if left == 1 else 'tries'} left.")

    used = OTPCode.objects.filter(pk=otp.pk, used_at__isnull=True).update(used_at=timezone.now())
    if not used:                       # someone used it a moment ago
        raise OTPError("Please request a new code.")
    return True