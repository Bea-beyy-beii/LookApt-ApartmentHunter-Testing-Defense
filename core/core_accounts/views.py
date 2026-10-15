from abc import ABC, abstractmethod

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from django.views.generic import RedirectView, TemplateView
from core.core_inquiries.services import NotificationFeed
from core.core_reports.services import SUPPORT_EMAIL
from core.core_admin.notify import Welcome

from .account import Account
from .legal import LegalContextMixin
from .otp import OTPError
from .throttle import LoginAttempts, RateLimitMixin
from .services import (GoogleSignIn, GoogleSignInError, NewPasswordStep, PasswordReset, SignIn, SignUp, SignUpForm)


# ------------------------------------------------------------------ shared by the code pages

class EmailCodeFlowMixin:
    """For views of an EmailCodeFlow (sign-up or forgot password): `self.flow` is
    that flow, `start_url` is its first page and `code_url` its code page."""

    flow_class = None
    start_url = None
    code_url = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.flow = self.flow_class(request)

    def send_code(self):
        """Email a code. True if sent; otherwise the reason is shown as a message."""
        try:
            self.flow.send_code()
        except OTPError as e:
            messages.error(self.request, str(e))
            return False
        return True

    def not_started(self):
        return redirect(self.start_url)


class SignUpFlowMixin(EmailCodeFlowMixin):
    flow_class = SignUp
    start_url = 'signup'
    code_url = 'otp'


class PasswordResetFlowMixin(EmailCodeFlowMixin):
    flow_class = PasswordReset
    start_url = 'forgot_password'
    code_url = 'forgot_password_code'


class CodePageView(ABC, View):
    """Enter the 6-digit code (sign-up and forgot password share otp.html).
    Template Method: subclasses say what happens once the code is right."""

    def get(self, request):
        if not self.flow.started:
            return self.not_started()
        return render(request, 'core_accounts/otp.html', self.page_context())

    def post(self, request):
        if not self.flow.started:
            return self.not_started()
        code = request.POST.get('code') or ''.join(request.POST.get(f'otp_{i}', '') for i in range(1, 7))
        try:
            self.flow.verify(code)
        except OTPError as e:
            messages.error(request, str(e))
            return redirect(self.code_url)
        return self.verified()

    def page_context(self):
        code = self.flow.code
        return {
            'masked_target': code.masked_target,
            'expires_in': code.seconds_until_expiry,
            'resend_in': code.seconds_until_resend,
        }

    @abstractmethod
    def verified(self):
        """The code was right: the response to send."""


class CodeResendView(View):
    """Resend: email a new code (allowed 60 s after the last one)."""

    def post(self, request):
        if not self.flow.started:
            return redirect(self.start_url)
        if self.send_code():
            messages.success(request, "We sent a new code to your email.")
        return redirect(self.code_url)


# ------------------------------------------------------------------ SIGN-UP

SIGNUP_FIELDS = ('first_name', 'last_name', 'phone_number', 'email', 'sex', 'role', 'agree_terms')


class SignUpView(RateLimitMixin, LegalContextMixin, SignUpFlowMixin, TemplateView):
    """Sign-up in 5 steps (Name, Contact, Profile, Security, Terms) on one page.
    Next / Back are handled by signup.js; each Next is checked by SignUpCheckView.
    "Create Account" checks everything again, keeps the sign-up in the session
    and sends the user to the OTP page, which creates the account
    (SignUp.create_account) once the code is verified."""

    template_name = 'core_accounts/signup.html'

    # "Create Account" at most 10 times an hour from one address (slows down
    # scripts testing which emails / phone numbers already have an account)
    rate_scope = 'signup'
    rate_limit = 10
    rate_window = 60 * 60
    rate_methods = ('POST',)

    def rate_limited(self, limit):
        messages.error(self.request, f"Too many sign-up attempts. Please try again in {limit.minutes_left} minutes.")
        return self.render_to_response(self.get_context_data(
            form_data={f: self.request.POST.get(f, '') for f in SIGNUP_FIELDS}), status=429)

    def get_context_data(self, **kwargs):
        # Coming back from the OTP page: keep what they typed (except the password).
        # From the preview's "Sign up" buttons (?role=renter / landlord): that role is picked already.
        kwargs.setdefault('form_data', self.flow.pending or {'role': self.request.GET.get('role', '')})
        kwargs.setdefault('start_step', 1)
        return super().get_context_data(**kwargs)

    def post(self, request):
        cleaned, errors, first_bad = SignUpForm(request.POST).check()
        if errors:
            return self.render_to_response(self.get_context_data(
                form_data={f: request.POST.get(f, '') for f in SIGNUP_FIELDS},
                errors=errors,
                start_step=first_bad,
            ))
        self.flow.start(cleaned)
        self.send_code()
        return redirect('otp')


class SignUpCheckView(RateLimitMixin, View):
    """Next button: check one step. {"ok": true} or {"ok": false, "errors": {field: message}}."""

    rate_scope = 'signup-check'
    rate_limit = 30                 # a real sign-up uses about 5
    rate_window = 10 * 60

    def rate_limited(self, limit):
        # Over the limit, Next stops checking (so a script learns nothing about
        # existing accounts); "Create Account" still checks everything
        return JsonResponse({'ok': True, 'errors': {}})

    def post(self, request):
        try:
            step = int(request.POST.get('step', ''))
        except ValueError:
            step = 0
        if step not in SignUpForm.STEPS:
            return JsonResponse({'ok': False, 'errors': {'step': 'Unknown step.'}}, status=400)
        errors = SignUpForm(request.POST).check_step(step)
        return JsonResponse({'ok': not errors, 'errors': errors})


class SignUpCodeView(SignUpFlowMixin, CodePageView):
    """Enter the 6-digit code sent after "Create Account"; a right code creates the account."""

    def not_started(self):
        messages.error(self.request, "Please fill in the sign-up form first.")
        return super().not_started()

    def verified(self):
        """Creates the account from the pending sign-up, logs in, opens the dashboard."""
        try:
            user = self.flow.create_account()
        except ValidationError as e:
            messages.error(self.request, "; ".join(e.messages))
            return redirect('signup')
        Welcome.for_user(user).send()
        SignIn(self.request).log_in(user)
        return redirect(user.home_url_name)


class SignUpResendView(SignUpFlowMixin, CodeResendView):
    pass


class LegalPageView(LegalContextMixin, TemplateView):
    template_name = 'core_accounts/legal/page.html'
    page = None
    page_title = None

    def get_context_data(self, **kwargs):
        return super().get_context_data(page=self.page, page_title=self.page_title, **kwargs)


class TermsView(LegalPageView):
    page = 'terms'
    page_title = 'Terms and Conditions'


class PrivacyView(LegalPageView):
    page = 'privacy'
    page_title = 'Privacy Notice'


# ------------------------------------------------------------------ LOG IN / OUT

class LoginView(View):
    template_name = 'core_accounts/login.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        identifier, password = request.POST.get('identifier', ''), request.POST.get('password', '')
        attempts = LoginAttempts(request, identifier)
        if attempts.blocked:                       # too many wrong passwords: don't even check this one
            messages.error(request, attempts.message)
            return render(request, self.template_name, status=429)
        sign_in = SignIn(request)
        user = sign_in.authenticate(identifier, password)
        if user:
            attempts.succeeded()
            sign_in.log_in(user)
            return redirect(user.home_url_name)
        if sign_in.is_suspended(identifier, password):
            messages.error(request, f"Your account is suspended. Please contact {SUPPORT_EMAIL}.")
        else:
            attempts.failed()
            messages.error(request, "Invalid phone/username or password.")
        return render(request, self.template_name)


class LogoutView(RedirectView):
    """Ends the session (the sidebar "Log Out" link used to only open the login page)."""

    pattern_name = 'login'

    def get_redirect_url(self, *args, **kwargs):
        logout(self.request)
        return super().get_redirect_url(*args, **kwargs)


# ------------------------------------------------------------------ FORGOT PASSWORD
# 1 Account (email + phone number) -> 2 Code (emailed, same page as sign-up's OTP) -> 3 New password

class ForgotPasswordView(RateLimitMixin, PasswordResetFlowMixin, View):
    """Step 1: which account? The email and the phone number must both be that account's.
    Then a code goes to the account's email."""

    # At most 10 tries an hour from one address (guessing email + phone pairs)
    rate_scope = 'forgot-password'
    rate_limit = 10
    rate_window = 60 * 60
    rate_methods = ('POST',)

    def rate_limited(self, limit):
        values = {name: self.request.POST.get(name, '').strip() for name in ('email', 'phone_number')}
        errors = {'email': f"Too many tries. Please try again in {limit.minutes_left} minutes."}
        response = self.page(values, errors)
        response.status_code = 429
        return response

    def get(self, request):
        return self.page({'email': '', 'phone_number': ''}, {})

    def post(self, request):
        values = {name: request.POST.get(name, '').strip() for name in ('email', 'phone_number')}
        user, errors = self.flow.check_account(values)
        if errors:
            return self.page(values, errors)
        self.flow.start(user)
        self.send_code()
        return redirect(self.code_url)

    def page(self, values, errors):
        return render(self.request, 'core_accounts/forgot_password.html', {'step': 1, 'errors': errors, **values})


class ForgotPasswordCodeView(PasswordResetFlowMixin, CodePageView):
    """Step 2: the 6-digit code (sign-up's OTP page, reset wording)."""

    def page_context(self):
        return {'reset': True, **super().page_context(), 'resend_url': reverse('forgot_password_resend')}

    def verified(self):
        self.flow.mark_verified()
        return redirect('forgot_password_new')


class ForgotPasswordResendView(PasswordResetFlowMixin, CodeResendView):
    pass


class ForgotPasswordNewView(PasswordResetFlowMixin, View):
    """Step 3: a new password (only right after a correct code)."""

    def dispatch(self, request, *args, **kwargs):
        verified_at = self.flow.verified_at
        if not verified_at or self.flow.expired:
            messages.error(request, "Please verify your email first." if not verified_at
                           else "That took too long. Please request a new code.")
            return redirect(self.start_url)
        self.user = self.flow.user
        if self.user is None:
            self.flow.cancel()
            return redirect(self.start_url)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return self.page({})

    def post(self, request):
        step = NewPasswordStep(self.user, request.POST)
        _, errors = step.clean()
        if errors:
            return self.page(errors)
        self.flow.finish(self.user, step.password)
        messages.success(request, "Your password has been updated. Log in with your new password.")
        return redirect('login')

    def page(self, errors):
        return render(self.request, 'core_accounts/forgot_password.html', {'step': 3, 'errors': errors})


# ------------------------------------------------------------------ GOOGLE SIGN-IN

class GoogleLoginView(View):
    """Continue with Google: send the user to Google's sign-in page."""

    def get(self, request):
        return redirect(GoogleSignIn(request).authorization_url())


class GoogleCallbackView(View):
    """Google sends the user back here with a one-time code."""

    def get(self, request):
        try:
            user = GoogleSignIn(request).user()
        except GoogleSignInError as error:
            messages.error(request, str(error))
            return redirect(error.redirect_to)
        SignIn(request).log_in(user)
        return redirect(user.home_url_name)


# ------------------------------------------------------------------ TOP BAR + Account pop-up (account.py)

class AccountActionView(LoginRequiredMixin, View):
    """The top bar's and the Account pop-up's JSON calls: logged in, `self.account` is theirs."""

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.account = Account(request.user)


class AvatarView(AccountActionView):
    """Profile tab: upload a photo (avatar) or remove it (remove=1)."""

    def post(self, request):
        try:
            if request.POST.get('remove'):
                self.account.remove_avatar()
            else:
                self.account.save_avatar(request.FILES.get('avatar'))
        except ValidationError as error:
            return JsonResponse({'error': ' '.join(error.messages)}, status=400)
        return JsonResponse(self.account.avatar_json)


class ContactSharingView(AccountActionView):
    """Settings tab: which of email / phone the other side may see."""

    def post(self, request):
        self.account.set_contact_sharing(request.POST.get('share_email') == '1', request.POST.get('share_phone') == '1')
        return JsonResponse({'share_email': request.user.share_email, 'share_phone': request.user.share_phone})


class ChangePasswordView(AccountActionView):
    """Settings tab: change password (stays logged in)."""

    def post(self, request):
        errors = self.account.change_password(request.POST)
        if errors:
            return JsonResponse({'ok': False, 'errors': errors}, status=400)
        update_session_auth_hash(request, request.user)
        return JsonResponse({'ok': True})


class ThemeView(AccountActionView):
    """Dark mode switch: saves 'light' / 'dark' on the account."""

    def post(self, request):
        theme = request.POST.get('theme', '')
        if not self.account.set_theme(theme):
            return JsonResponse({'error': 'Unknown theme.'}, status=400)
        return JsonResponse({'theme': theme})


class NotificationsView(AccountActionView):
    """The bell's dropdown list (rendered HTML) + how many arrived since it was last opened."""

    def get(self, request):
        items = NotificationFeed.for_user(request.user).items()
        html = render_to_string('core_accounts/partials/notification_items.html',
                                {'notifications': items[:5]}, request=request)
        return JsonResponse({'html': html, 'new_count': sum(1 for n in items if n['is_new'])})


class NotificationsSeenView(AccountActionView):
    """Opening the bell clears its red dot."""

    def post(self, request):
        self.account.mark_notifications_seen()
        return JsonResponse({'new_count': 0})


class NotificationsClearView(AccountActionView):
    """"Clear all" (bell + Inquiries panel): hides everything so far; newer ones still show."""

    def post(self, request):
        self.account.clear_notifications()
        return JsonResponse({'cleared': True})
