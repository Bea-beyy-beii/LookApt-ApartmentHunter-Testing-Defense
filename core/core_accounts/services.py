from django.contrib.auth import password_validation
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from core.models import User, Renter, Landlord, phone_regex

# Session key for a sign-up that passed all 4 steps and waits for the OTP
PENDING_SIGNUP = 'pending_signup'


class AccountService:
    ROLE_PROFILES = {'renter': Renter, 'landlord': Landlord}

    # Sign-up steps: 1 Name · 2 Contact · 3 Profile · 4 Security
    STEPS = {
        1: ('first_name', 'last_name'),
        2: ('phone_number', 'email'),
        3: ('sex', 'role'),
        4: ('password', 'confirm_password'),
    }

    # ------------------------------------------------------------------ sign-up steps

    @classmethod
    def clean_step(cls, step, data, earlier=None):
        """Check one sign-up step. Returns (cleaned values, {field: error}).

        earlier: values from the steps before it (step 4 needs the name /
        email so a password can't just be your name).
        """
        get = lambda field: (data.get(field) or '').strip()
        cleaned, errors = {}, {}

        if step == 1:
            for field, label in (('first_name', 'First name'), ('last_name', 'Last name')):
                value = ' '.join(get(field).split())
                if not value:
                    errors[field] = f"{label} is required."
                elif len(value) > 150:
                    errors[field] = f"{label} is too long."
                elif not any(ch.isalpha() for ch in value):
                    errors[field] = f"Enter a valid {label.lower()}."
                cleaned[field] = value

        elif step == 2:
            phone = get('phone_number').replace(' ', '').replace('-', '')
            try:
                phone_regex(phone)
            except ValidationError:
                errors['phone_number'] = "Enter an 11-digit number starting with 09."
            else:
                if User.objects.filter(phone_number=phone).exists():
                    errors['phone_number'] = "That phone number is already registered."
            cleaned['phone_number'] = phone

            email = get('email').lower()
            try:
                validate_email(email)
            except ValidationError:
                errors['email'] = "Enter a valid email address." if email else "Email is required."
            else:
                if User.objects.filter(email__iexact=email).exists():
                    errors['email'] = "That email is already registered."
            cleaned['email'] = email

        elif step == 3:
            sex, role = get('sex'), get('role')
            if sex not in dict(User.SEX_CHOICES):
                errors['sex'] = "Select your sex."
            if role not in cls.ROLE_PROFILES:
                errors['role'] = "Select whether you're a renter or a landlord."
            cleaned.update(sex=sex, role=role)

        elif step == 4:
            password, confirm = data.get('password') or '', data.get('confirm_password') or ''
            if not password:
                errors['password'] = "Password is required."
            else:
                # Same rules as settings.AUTH_PASSWORD_VALIDATORS (length, common, numeric, too similar)
                try:
                    password_validation.validate_password(password, User(**(earlier or {})))
                except ValidationError as e:
                    errors['password'] = " ".join(e.messages)
            if not errors.get('password') and password != confirm:
                errors['confirm_password'] = "Passwords do not match."
            cleaned['password'] = password

        else:
            errors['step'] = "Unknown step."

        return cleaned, errors

    @classmethod
    def clean_signup(cls, data):
        """All 4 steps (the final "Create Account"). Returns (cleaned, errors, first step with an error)."""
        cleaned, errors, first_bad = {}, {}, None
        for step in cls.STEPS:
            earlier = {k: v for k, v in cleaned.items() if k in ('first_name', 'last_name', 'email')}
            values, step_errors = cls.clean_step(step, data, earlier)
            cleaned.update(values)
            errors.update(step_errors)
            if step_errors and first_bad is None:
                first_bad = step
        return cleaned, errors, first_bad

    # ------------------------------------------------------------------ waiting for the OTP

    @staticmethod
    def start_pending_signup(request, cleaned):
        """Keep the checked sign-up in the session until the OTP is confirmed.
        The password is stored hashed, never as plain text."""
        pending = {k: v for k, v in cleaned.items() if k != 'password'}
        pending['password_hash'] = make_password(cleaned['password'])
        request.session[PENDING_SIGNUP] = pending

    @staticmethod
    def pending_signup(request):
        """The sign-up waiting for its OTP (dict without the password), or None."""
        pending = request.session.get(PENDING_SIGNUP)
        return {k: v for k, v in pending.items() if k != 'password_hash'} if pending else None

    @classmethod
    @transaction.atomic
    def create_pending_account(cls, request):
        """Call this once the OTP is verified: creates the account from the
        session and returns the user. Raises ValidationError if there's no
        pending sign-up or the phone / email got taken in the meantime."""
        pending = request.session.get(PENDING_SIGNUP)
        if not pending:
            raise ValidationError("Your sign-up expired. Please start again.")

        if User.objects.filter(phone_number=pending['phone_number']).exists():
            raise ValidationError("That phone number is already registered.")
        if User.objects.filter(email__iexact=pending['email']).exists():
            raise ValidationError("That email is already registered.")

        user = User(first_name=pending['first_name'], last_name=pending['last_name'],
                    phone_number=pending['phone_number'], email=pending['email'],
                    sex=pending['sex'], role=pending['role'])
        user.full_clean(exclude=['username', 'password'])
        user.password = pending['password_hash']
        try:
            user.save()
        except IntegrityError:
            raise ValidationError("That phone number or email is already registered.")
        cls.ROLE_PROFILES[user.role].objects.create(user=user)
        del request.session[PENDING_SIGNUP]
        return user

    # ------------------------------------------------------------------ direct registration

    @classmethod
    @transaction.atomic
    def register(cls, first_name, last_name, phone_number, email, sex, role, password):
        if role not in cls.ROLE_PROFILES:
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
        cls.ROLE_PROFILES[role].objects.create(user=user)
        return user