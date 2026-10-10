import secrets
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
from . import otp
from .services import AccountService


ROLE_HOME = {
    'renter': 'core_renters:dashboard',
    'landlord': 'core_landlords:dashboard',
    'admin': 'admin:index',
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
        _send_signup_code(request, otp.Channel.SMS)
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
    request.session.pop(OTP_CHANNEL, None)
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
        messages.error(request, "Invalid phone/username or password.")
    return render(request, 'core_accounts/login.html')

def logout_view(request):
    # Ends the session (the sidebar "Log Out" link used to only open the login page)
    logout(request)
    return redirect('login')

# ------------------------------------------------------------------ SIGN-UP CODE (5th step)

OTP_CHANNEL = 'otp_channel'     # session: where the sign-up code went (sms / email)


def _signup_target(pending, channel):
    return pending['email'] if channel == otp.Channel.EMAIL else pending['phone_number']


def _send_signup_code(request, channel):
    """Send a sign-up code to the pending sign-up's phone (sms) or email. True if sent."""
    pending = AccountService.pending_signup(request)
    request.session[OTP_CHANNEL] = channel
    try:
        otp.send_code(otp.Purpose.SIGNUP, channel, _signup_target(pending, channel))
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

    channel = request.session.get(OTP_CHANNEL, otp.Channel.SMS)
    target = _signup_target(pending, channel)

    if request.method == 'POST':
        code = request.POST.get('code') or ''.join(request.POST.get(f'otp_{i}', '') for i in range(1, 7))
        try:
            otp.verify_code(otp.Purpose.SIGNUP, target, code, channel)
        except otp.OTPError as e:
            messages.error(request, str(e))
            return redirect('otp')
        return finish_signup(request)

    return render(request, 'core_accounts/otp.html', {
        'channel': channel,
        'masked_target': otp.mask(channel, target),
        'expires_in': otp.seconds_until_expiry(otp.Purpose.SIGNUP, target),
        'resend_in': otp.seconds_until_resend(otp.Purpose.SIGNUP, target),
        'other_channel': otp.Channel.SMS if channel == otp.Channel.EMAIL else otp.Channel.EMAIL,
    })


@require_POST
def otp_resend_view(request):
    """Resend: a new code to the same place, or switch between phone and email."""
    if not AccountService.pending_signup(request):
        return redirect('signup')
    channel = request.POST.get('channel', request.session.get(OTP_CHANNEL, otp.Channel.SMS))
    if channel not in otp.Channel.values:
        channel = otp.Channel.SMS
    if _send_signup_code(request, channel):
        where = "email" if channel == otp.Channel.EMAIL else "phone"
        messages.success(request, f"We sent a new code to your {where}.")
    return redirect('otp')


# ------------------------------------------------------------------ TOP BAR (dark mode switch + bell)

def otp_view(request):
    return render(request, 'core_accounts/otp.html')


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