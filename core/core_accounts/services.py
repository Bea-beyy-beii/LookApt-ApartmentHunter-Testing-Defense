"""
Signing up, logging in and resetting a password.

    SignUpForm(data)          checks the 5 sign-up steps (one SignUpStep subclass per step)
    SignUp(request)           the sign-up waiting in the session for its emailed code
    PasswordReset(request)    forgot password: account -> emailed code -> new password
    SignIn(request)           logging in ("Welcome" vs "Welcome back")
    GoogleSignIn(request)     Continue with Google

SignUp and PasswordReset are both an EmailCodeFlow: something kept in the
session until the user types the code we emailed them.
"""
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth import authenticate, login, password_validation
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from core.models import User, Profile, phone_regex

from .legal import TERMS_VERSION
from .otp import OneTimeCode, Purpose


# ------------------------------------------------------------------ sign-up steps

class SignUpStep(ABC):
    """One step of the sign-up form.

    Template Method: clean() is the same for every step, each subclass
    only fills in _check() with its own rules.
    """

    number = None
    fields = ()

    def __init__(self, data, earlier=None):
        self.data = data
        self.earlier = earlier or {}     # values from the steps before it (the password step needs the name / email)
        self.cleaned, self.errors = {}, {}

    def _get(self, field):
        return (self.data.get(field) or '').strip()

    def clean(self):
        """Returns (cleaned values, {field: error})."""
        self._check()
        return self.cleaned, self.errors

    @abstractmethod
    def _check(self):
        """Fill self.cleaned and self.errors."""


class NameStep(SignUpStep):
    number = 1
    fields = ('first_name', 'last_name')

    def _check(self):
        for field, label in (('first_name', 'First name'), ('last_name', 'Last name')):
            value = ' '.join(self._get(field).split())
            if not value:
                self.errors[field] = f"{label} is required."
            elif len(value) > 150:
                self.errors[field] = f"{label} is too long."
            elif not any(ch.isalpha() for ch in value):
                self.errors[field] = f"Enter a valid {label.lower()}."
            self.cleaned[field] = value


class ContactStep(SignUpStep):
    number = 2
    fields = ('phone_number', 'email')

    def _check(self):
        phone = self._get('phone_number').replace(' ', '').replace('-', '')
        try:
            phone_regex(phone)
        except ValidationError:
            self.errors['phone_number'] = "Enter an 11-digit number starting with 09."
        else:
            if User.objects.filter(phone_number=phone).exists():
                self.errors['phone_number'] = "That phone number is already registered."
        self.cleaned['phone_number'] = phone

        email = self._get('email').lower()
        try:
            validate_email(email)
        except ValidationError:
            self.errors['email'] = "Enter a valid email address." if email else "Email is required."
        else:
            if User.objects.filter(email__iexact=email).exists():
                self.errors['email'] = "That email is already registered."
        self.cleaned['email'] = email


class ProfileStep(SignUpStep):
    number = 3
    fields = ('sex', 'role')

    def _check(self):
        sex, role = self._get('sex'), self._get('role')
        if sex not in dict(User.SEX_CHOICES):
            self.errors['sex'] = "Select your sex."
        if Profile.for_role(role) is None:
            self.errors['role'] = "Select whether you're a renter or a landlord."
        self.cleaned.update(sex=sex, role=role)


class SecurityStep(SignUpStep):
    number = 4
    fields = ('password', 'confirm_password')

    def _check(self):
        password, confirm = self.data.get('password') or '', self.data.get('confirm_password') or ''
        if not password:
            self.errors['password'] = "Password is required."
        else:
            # Same rules as settings.AUTH_PASSWORD_VALIDATORS (length, common, numeric, too similar)
            try:
                password_validation.validate_password(password, User(**self.earlier))
            except ValidationError as e:
                self.errors['password'] = " ".join(e.messages)
        if not self.errors.get('password') and password != confirm:
            self.errors['confirm_password'] = "Passwords do not match."
        self.cleaned['password'] = password


class TermsStep(SignUpStep):
    number = 5
    fields = ('agree_terms',)

    def _check(self):
        # signup.js only unlocks the box after reading to the end; here we just need it checked
        if not self.data.get('agree_terms'):
            self.errors['agree_terms'] = "Please read and agree to the Terms and Conditions and the Privacy Notice."
        self.cleaned['agree_terms'] = True


class NewPasswordStep(SecurityStep):
    """Forgot password step 3 and Settings > Change password: the sign-up password
    rules (inherited), and it can't be the current password."""

    def __init__(self, user, data):
        super().__init__(data, {'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email})
        self.user = user

    def _check(self):
        super()._check()
        if not self.errors and self.user.check_password(self.cleaned['password']):
            self.errors['password'] = "That's your current password. Please choose a new one."

    @property
    def password(self):
        return self.cleaned.get('password', '')


class SignUpForm:
    """The sign-up form's data: 1 Name · 2 Contact · 3 Profile · 4 Security · 5 Terms."""

    STEPS = {step.number: step for step in (NameStep, ContactStep, ProfileStep, SecurityStep, TermsStep)}
    SIMILARITY_FIELDS = ('first_name', 'last_name', 'email')     # what a password can't look like

    def __init__(self, data):
        self.data = data

    def check_step(self, number):
        """The Next button: {field: error} for one step."""
        earlier = {}
        if number == SecurityStep.number:   # the password can't be too similar to the name / email
            for previous in (NameStep, ContactStep):
                values, _ = previous(self.data).clean()
                earlier.update({k: v for k, v in values.items() if k != 'phone_number'})
        _, errors = self.STEPS[number](self.data, earlier).clean()
        return errors

    def check(self):
        """All 5 steps (the final "Create Account"). Returns (cleaned, errors, first step with an error)."""
        cleaned, errors, first_bad = {}, {}, None
        for number, step_class in self.STEPS.items():
            earlier = {k: v for k, v in cleaned.items() if k in self.SIMILARITY_FIELDS}
            values, step_errors = step_class(self.data, earlier).clean()
            cleaned.update(values)
            errors.update(step_errors)
            if step_errors and first_bad is None:
                first_bad = number
        return cleaned, errors, first_bad


# ------------------------------------------------------------------ waiting for an emailed code

class EmailCodeFlow(ABC):
    """Something kept in the session until the user types the code we emailed.
    Each subclass says where it lives in the session and whose email gets the code."""

    session_key = None
    purpose = None

    def __init__(self, request):
        self.request = request
        self.session = request.session

    @property
    def data(self):
        return self.session.get(self.session_key)

    @property
    def started(self):
        return bool(self.data)

    @property
    @abstractmethod
    def email(self):
        """Where the code goes."""

    @property
    @abstractmethod
    def name(self):
        """The first name for the email's greeting."""

    @property
    def code(self):
        return OneTimeCode(self.purpose, self.email)

    def send_code(self):
        """Raises OTPError (too soon, couldn't send ...)."""
        self.code.send(name=self.name)

    def verify(self, entered):
        """Raises OTPError if the code is wrong."""
        self.code.verify(entered)

    def cancel(self):
        self.session.pop(self.session_key, None)


class SignUp(EmailCodeFlow):
    """A sign-up that passed all 5 steps and waits for its OTP."""

    session_key = 'pending_signup'
    purpose = Purpose.SIGNUP

    @property
    def email(self):
        return self.data['email']

    @property
    def name(self):
        return self.data['first_name']

    def start(self, cleaned):
        """Keep the checked sign-up in the session until the OTP is confirmed.
        The password is stored hashed, never as plain text."""
        pending = {k: v for k, v in cleaned.items() if k != 'password'}
        pending['password_hash'] = make_password(cleaned['password'])
        self.session[self.session_key] = pending

    @property
    def pending(self):
        """The sign-up waiting for its OTP (dict without the password), or None."""
        pending = self.data
        return {k: v for k, v in pending.items() if k != 'password_hash'} if pending else None

    @transaction.atomic
    def create_account(self):
        """Call this once the OTP is verified: creates the account from the
        session and returns the user. Raises ValidationError if there's no
        pending sign-up or the phone / email got taken in the meantime."""
        pending = self.data
        if not pending:
            raise ValidationError("Your sign-up expired. Please start again.")

        if User.objects.filter(phone_number=pending['phone_number']).exists():
            raise ValidationError("That phone number is already registered.")
        if User.objects.filter(email__iexact=pending['email']).exists():
            raise ValidationError("That email is already registered.")

        if not pending.get('agree_terms'):
            raise ValidationError("Please agree to the Terms and Conditions and the Privacy Notice.")

        user = User(first_name=pending['first_name'], last_name=pending['last_name'],
                    phone_number=pending['phone_number'], email=pending['email'],
                    sex=pending['sex'], role=pending['role'],
                    terms_version=TERMS_VERSION, terms_accepted_at=timezone.now())
        user.full_clean(exclude=['username', 'password'])
        user.password = pending['password_hash']
        try:
            user.save()
        except IntegrityError:
            raise ValidationError("That phone number or email is already registered.")
        user.create_profile()
        del self.session[self.session_key]
        return user

    @staticmethod
    @transaction.atomic
    def register(first_name, last_name, phone_number, email, sex, role, password):
        """Direct registration, without the steps or the code."""
        if Profile.for_role(role) is None:
            raise ValidationError("Invalid role.")
        if not password or len(password) < 8:
            raise ValidationError("Password must be at least 8 characters.")
        email = (email or '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("That email is already registered.")

        user = User(first_name=first_name, last_name=last_name,
                    phone_number=phone_number, email=email, sex=sex, role=role)
        user.full_clean(exclude=['username', 'password'])
        user.set_password(password)
        user.save()
        user.create_profile()
        return user


class PasswordReset(EmailCodeFlow):
    """Forgot password: 1 Account (email + phone number) -> 2 Code -> 3 New password.
    Session data: {'user_id', 'email', 'name', 'verified_at'}."""

    session_key = 'password_reset'
    purpose = Purpose.RESET
    WINDOW = timedelta(minutes=10)      # time to choose a new password after the code

    @property
    def email(self):
        return self.data['email']

    @property
    def name(self):
        return self.data['name']

    @staticmethod
    def find_account(email, phone_number):
        """The active account with this email AND this phone number. None if they don't
        belong to the same account, so another person's email alone isn't enough."""
        email = (email or '').strip()
        phone_number = (phone_number or '').replace(' ', '').replace('-', '')
        if not email or not phone_number:
            return None
        return User.objects.filter(email__iexact=email, phone_number=phone_number, is_active=True).first()

    def check_account(self, values):
        """Step 1. Returns (user or None, {field: error})."""
        errors = {}
        if not values['email']:
            errors['email'] = "Enter the email on your account."
        else:
            try:
                validate_email(values['email'])
            except ValidationError:
                errors['email'] = "Enter a valid email address."
        if not values['phone_number']:
            errors['phone_number'] = "Enter the phone number on your account."
        if errors:
            return None, errors

        user = self.find_account(values['email'], values['phone_number'])
        if user is None:
            # Same message whether the email exists or not: it doesn't tell who has an account
            errors['email'] = "That email and phone number don't belong to the same account."
        return user, errors

    def start(self, user):
        self.session[self.session_key] = {
            'user_id': str(user.pk), 'email': user.email.lower(), 'name': user.first_name, 'verified_at': None,
        }

    def mark_verified(self):
        data = self.data
        data['verified_at'] = timezone.now().isoformat()
        self.session[self.session_key] = data

    @property
    def verified_at(self):
        data = self.data
        return data and data.get('verified_at')

    @property
    def expired(self):
        return timezone.now() - datetime.fromisoformat(self.verified_at) > self.WINDOW

    @property
    def user(self):
        return User.objects.filter(pk=self.data['user_id'], is_active=True).first()

    def finish(self, user, password):
        user.set_password(password)              # also signs the account out everywhere else
        user.save(update_fields=['password'])
        self.cancel()


# ------------------------------------------------------------------ log in

class SignIn:
    """Logging in with a phone number / username / email and a password."""

    FIRST_VISIT = 'first_visit'      # session: True during the account's very first log-in

    def __init__(self, request):
        self.request = request

    def authenticate(self, identifier, password):
        return authenticate(self.request, username=identifier, password=password)

    def log_in(self, user):
        """Log the user in, remembering whether it's their first time ("Welcome" vs "Welcome back")."""
        first_time = user.last_login is None      # login() sets last_login, so look before
        login(self.request, user)
        self.request.session[self.FIRST_VISIT] = first_time

    @property
    def first_visit(self):
        return self.request.session.get(self.FIRST_VISIT, False)

    @staticmethod
    def is_suspended(identifier, password):
        """For the login page: the right password, but an admin suspended the account."""
        identifier = (identifier or '').strip()
        if not identifier or not password:
            return False
        user = User.objects.filter(
            Q(username__iexact=identifier) | Q(phone_number=identifier) | Q(email__iexact=identifier),
            is_active=False, suspended_at__isnull=False,
        ).first()
        return bool(user and user.check_password(password))


class GoogleSignInError(Exception):
    """Google sign-in didn't work: a message for the user and the page to go back to."""

    def __init__(self, message, redirect_to='login'):
        super().__init__(message)
        self.redirect_to = redirect_to


class GoogleSignIn:
    """Continue with Google (OAuth): send the user to Google, then read who came back."""

    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
    STATE = 'google_oauth_state'

    def __init__(self, request):
        self.request = request

    @property
    def _redirect_uri(self):
        return self.request.build_absolute_uri(reverse('google_callback'))

    def authorization_url(self):
        """Google's sign-in page."""
        state = secrets.token_urlsafe(32)          # proves the reply belongs to this browser
        self.request.session[self.STATE] = state
        params = {
            'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
            'redirect_uri': self._redirect_uri,
            'response_type': 'code',
            'scope': 'openid email profile',
            'state': state,
            'prompt': 'select_account',
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def _user_info(self, code):
        token = requests.post(self.TOKEN_URL, data={
            'code': code,
            'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
            'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
            'redirect_uri': self._redirect_uri,
            'grant_type': 'authorization_code',
        }, timeout=10)
        token.raise_for_status()
        info = requests.get(self.USERINFO_URL, timeout=10,
                            headers={'Authorization': f"Bearer {token.json()['access_token']}"})
        info.raise_for_status()
        return info.json()

    def user(self):
        """Google sent the user back with a one-time code: their LookApt account.
        Raises GoogleSignInError."""
        query = self.request.GET
        state = self.request.session.pop(self.STATE, None)
        if not state or query.get('state') != state or 'code' not in query:
            raise GoogleSignInError("Google sign-in was cancelled or expired. Please try again.")

        try:
            info = self._user_info(query['code'])
        except (requests.RequestException, KeyError, ValueError):
            raise GoogleSignInError("Couldn't reach Google. Please try again.")

        if not info.get('email_verified'):
            raise GoogleSignInError("Your Google email isn't verified.")

        user = User.objects.filter(email__iexact=info['email']).first()
        if user is None or not user.is_active:
            raise GoogleSignInError(f"No LookApt account uses {info['email']}. Sign up first.", 'signup')
        return user
