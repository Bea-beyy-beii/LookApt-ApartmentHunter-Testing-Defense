import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode
import requests
from django.conf import settings
from django.urls import reverse
from core.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from core.core_inquiries.services import notifications_for
from core.core_reports.services import SUPPORT_EMAIL
from core.core_admin import notify

from . import otp
from .services import AccountService


ROLE_HOME = {
    'renter': 'core_renters:dashboard',
    'landlord': 'core_landlords:dashboard',
    'admin': 'core_admin:overview',
}

SIGNUP_FIELDS = ('first_name', 'last_name', 'phone_number', 'email', 'sex', 'role')


def signup_view(request):
    """Sign-up in 4 steps (Name, Contact, Profile, Security) on one page.
    Next / Back are handled by signup.js; each Next is checked by signup_check_view.
    "Create Account" checks everything again, keeps the sign-up in the session
    and sends the user to the OTP page, which creates the account
    (AccountService.create_pending_account) once the code is verified."""
    if request.method == 'POST':
        cleaned, errors, first_bad = AccountService.clean_signup(request.POST)
        if errors:
            return render(request, 'core_accounts/signup.html', {
                'form_data': {f: request.POST.get(f, '') for f in SIGNUP_FIELDS},
                'errors': errors,
                'start_step': first_bad,
            })
        AccountService.start_pending_signup(request, cleaned)
        _send_signup_code(request)
        return redirect('otp')

    # Coming back from the OTP page: keep what they typed (except the password)
    return render(request, 'core_accounts/signup.html', {
        'form_data': AccountService.pending_signup(request) or {},
        'start_step': 1,
    })


def finish_signup(request):
    """For the OTP view: call this once the code is verified.
    Creates the account from the pending sign-up, logs in, opens the dashboard."""
    try:
        user = AccountService.create_pending_account(request)
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect('signup')
    notify.welcome(user)
    login(request, user)
    return redirect(ROLE_HOME[user.role])


@require_POST
def signup_check_view(request):
    """Next button: check one step. {"ok": true} or {"ok": false, "errors": {field: message}}."""
    try:
        step = int(request.POST.get('step', ''))
    except ValueError:
        step = 0
    if step not in AccountService.STEPS:
        return JsonResponse({'ok': False, 'errors': {'step': 'Unknown step.'}}, status=400)

    earlier = {}
    if step == 4:   # the password can't be too similar to the name / email
        for previous in (1, 2):
            values, _ = AccountService.clean_step(previous, request.POST)
            earlier.update({k: v for k, v in values.items() if k != 'phone_number'})
    _, errors = AccountService.clean_step(step, request.POST, earlier)
    return JsonResponse({'ok': not errors, 'errors': errors})

def login_view(request):
    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('identifier', ''),
            password=request.POST.get('password', ''),
        )
        if user:
            login(request, user)
            return redirect(ROLE_HOME[user.role])
        if AccountService.is_suspended(request.POST.get('identifier', ''), request.POST.get('password', '')):
            messages.error(request, f"Your account is suspended. Please contact {SUPPORT_EMAIL}.")
        else:
            messages.error(request, "Invalid phone/username or password.")
    return render(request, 'core_accounts/login.html')

def logout_view(request):
    # Ends the session (the sidebar "Log Out" link used to only open the login page)
    logout(request)
    return redirect('login')

# ------------------------------------------------------------------ SIGN-UP CODE (5th step, by email)

def _send_signup_code(request):
    """Email a sign-up code to the pending sign-up's email. True if sent."""
    pending = AccountService.pending_signup(request)
    try:
        otp.send_code(otp.Purpose.SIGNUP, pending['email'], name=pending['first_name'])
    except otp.OTPError as e:
        messages.error(request, str(e))
        return False
    return True


def otp_view(request):
    """Enter the 6-digit code sent after "Create Account"; a right code creates the account."""
    pending = AccountService.pending_signup(request)
    if not pending:
        messages.error(request, "Please fill in the sign-up form first.")
        return redirect('signup')

    email = pending['email']

    if request.method == 'POST':
        code = request.POST.get('code') or ''.join(request.POST.get(f'otp_{i}', '') for i in range(1, 7))
        try:
            otp.verify_code(otp.Purpose.SIGNUP, email, code)
        except otp.OTPError as e:
            messages.error(request, str(e))
            return redirect('otp')
        return finish_signup(request)

    return render(request, 'core_accounts/otp.html', {
        'masked_target': otp.mask(email),
        'expires_in': otp.seconds_until_expiry(otp.Purpose.SIGNUP, email),
        'resend_in': otp.seconds_until_resend(otp.Purpose.SIGNUP, email),
    })


@require_POST
def otp_resend_view(request):
    """Resend: email a new code (allowed 60 s after the last one)."""
    if not AccountService.pending_signup(request):
        return redirect('signup')
    if _send_signup_code(request):
        messages.success(request, "We sent a new code to your email.")
    return redirect('otp')

# ------------------------------------------------------------------ FORGOT PASSWORD
# 1 Account (email or phone) -> 2 Code (emailed, same page as sign-up's OTP) -> 3 New password

RESET = 'password_reset'               # session: {'user_id', 'email', 'name', 'verified_at'}
RESET_WINDOW = timedelta(minutes=10)   # time to choose a new password after the code


def _reset_data(request):
    return request.session.get(RESET)


def _send_reset_code(request, data):
    try:
        otp.send_code(otp.Purpose.RESET, data['email'], name=data['name'])
    except otp.OTPError as e:
        messages.error(request, str(e))
        return False
    return True


def forgot_password_view(request):
    """Step 1: which account? Then a code goes to the account's email."""
    identifier, error = '', ''
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        user = AccountService.find_account(identifier)
        if not identifier:
            error = "Enter the email or phone number on your account."
        elif user is None:
            error = "We couldn't find an account with that email or phone number."
        elif not user.email:
            error = f"This account has no email address. Please contact {SUPPORT_EMAIL}."
        else:
            data = {'user_id': str(user.pk), 'email': user.email.lower(), 'name': user.first_name, 'verified_at': None}
            request.session[RESET] = data
            _send_reset_code(request, data)
            return redirect('forgot_password_code')

    return render(request, 'core_accounts/forgot_password.html', {
        'step': 1, 'identifier': identifier, 'errors': {'identifier': error} if error else {},
    })


def forgot_password_code_view(request):
    """Step 2: the 6-digit code (sign-up's OTP page, reset wording)."""
    data = _reset_data(request)
    if not data:
        return redirect('forgot_password')

    if request.method == 'POST':
        code = request.POST.get('code') or ''.join(request.POST.get(f'otp_{i}', '') for i in range(1, 7))
        try:
            otp.verify_code(otp.Purpose.RESET, data['email'], code)
        except otp.OTPError as e:
            messages.error(request, str(e))
            return redirect('forgot_password_code')
        data['verified_at'] = timezone.now().isoformat()
        request.session[RESET] = data
        return redirect('forgot_password_new')

    return render(request, 'core_accounts/otp.html', {
        'reset': True,
        'masked_target': otp.mask(data['email']),
        'expires_in': otp.seconds_until_expiry(otp.Purpose.RESET, data['email']),
        'resend_in': otp.seconds_until_resend(otp.Purpose.RESET, data['email']),
        'resend_url': reverse('forgot_password_resend'),
    })


@require_POST
def forgot_password_resend_view(request):
    data = _reset_data(request)
    if not data:
        return redirect('forgot_password')
    if _send_reset_code(request, data):
        messages.success(request, "We sent a new code to your email.")
    return redirect('forgot_password_code')


def forgot_password_new_view(request):
    """Step 3: a new password (only right after a correct code)."""
    data = _reset_data(request)
    verified_at = data and data.get('verified_at')
    if not verified_at or timezone.now() - datetime.fromisoformat(verified_at) > RESET_WINDOW:
        messages.error(request, "Please verify your email first." if not verified_at
                       else "That took too long. Please request a new code.")
        return redirect('forgot_password')
    user = User.objects.filter(pk=data['user_id'], is_active=True).first()
    if user is None:
        request.session.pop(RESET, None)
        return redirect('forgot_password')

    errors = {}
    if request.method == 'POST':
        password, errors = AccountService.clean_new_password(user, request.POST)
        if not errors:
            user.set_password(password)              # also signs the account out everywhere else
            user.save(update_fields=['password'])
            request.session.pop(RESET, None)
            messages.success(request, "Your password has been updated. Log in with your new password.")
            return redirect('login')

    return render(request, 'core_accounts/forgot_password.html', {'step': 3, 'errors': errors})


# ------------------------------------------------------------------ GOOGLE SIGN-IN

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def google_login_view(request):
    """Continue with Google: send the user to Google's sign-in page."""
    state = secrets.token_urlsafe(32)          # proves the reply belongs to this browser
    request.session['google_oauth_state'] = state
    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': request.build_absolute_uri(reverse('google_callback')),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


def google_callback_view(request):
    """Google sends the user back here with a one-time code."""
    state = request.session.pop('google_oauth_state', None)
    if not state or request.GET.get('state') != state or 'code' not in request.GET:
        messages.error(request, "Google sign-in was cancelled or expired. Please try again.")
        return redirect('login')

    try:
        token = requests.post(GOOGLE_TOKEN_URL, data={
            'code': request.GET['code'],
            'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
            'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
            'redirect_uri': request.build_absolute_uri(reverse('google_callback')),
            'grant_type': 'authorization_code',
        }, timeout=10)
        token.raise_for_status()
        info = requests.get(GOOGLE_USERINFO_URL, timeout=10,
                            headers={'Authorization': f"Bearer {token.json()['access_token']}"})
        info.raise_for_status()
        info = info.json()
    except (requests.RequestException, KeyError, ValueError):
        messages.error(request, "Couldn't reach Google. Please try again.")
        return redirect('login')

    if not info.get('email_verified'):
        messages.error(request, "Your Google email isn't verified.")
        return redirect('login')

    user = User.objects.filter(email__iexact=info['email']).first()
    if user is None or not user.is_active:
        messages.error(request, f"No LookApt account uses {info['email']}. Sign up first.")
        return redirect('signup')

    login(request, user)
    return redirect(ROLE_HOME[user.role])


# ------------------------------------------------------------------ TOP BAR (dark mode switch + bell)

@login_required
@require_POST
def theme_view(request):
    """Dark mode switch: saves 'light' / 'dark' on the account."""
    theme = request.POST.get('theme', '')
    if theme not in dict(request.user.THEME_CHOICES):
        return JsonResponse({'error': 'Unknown theme.'}, status=400)
    request.user.theme = theme
    request.user.save(update_fields=['theme'])
    return JsonResponse({'theme': theme})


@login_required
@require_GET
def notifications_view(request):
    """The bell's dropdown list (rendered HTML) + how many arrived since it was last opened."""
    items = notifications_for(request.user)
    html = render_to_string('core_accounts/partials/notification_items.html',
                            {'notifications': items[:5]}, request=request)
    return JsonResponse({'html': html, 'new_count': sum(1 for n in items if n['is_new'])})


@login_required
@require_POST
def notifications_seen_view(request):
    """Opening the bell clears its red dot."""
    request.user.notifications_seen_at = timezone.now()
    request.user.save(update_fields=['notifications_seen_at'])
    return JsonResponse({'new_count': 0})