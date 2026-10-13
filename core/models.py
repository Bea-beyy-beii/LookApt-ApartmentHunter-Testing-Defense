import uuid
import re
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db.models import CheckConstraint, Q

# --------------------------------------------------------------------------------------------------------------- REGEX FOR PHONE NUM

phone_regex = RegexValidator(
    regex=r'^09\d{9}$',
    message="Phone number must start with 09 and be exactly 11 digits."
)

# --------------------------------------------------------------------------------------------------------------- PROFILE PHOTOS

def avatar_path(instance, filename):
    # A new random name each upload, so browsers never show a cached old photo
    return f"avatars/{instance.pk}/{uuid.uuid4().hex}.webp"

# --------------------------------------------------------------------------------------------------------------- CLASS USER - FOR USERS TABLE

class User(AbstractUser):

# --------------------------------------------------------- ENUM FIELDS

    ROLE_CHOICES = [
        ('renter', 'Renter'),
        ('landlord', 'Landlord'),
        ('admin', 'Admin'),
    ]
    
    SEX_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
    ]

    REQUIRED_FIELDS = ['phone_number', 'sex', 'role']

# --------------------------------------------------------- COLUMNS FOR USERS TABLE

    user_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=150, blank=False)
    last_name = models.CharField(max_length=150, blank=False)
    phone_number = models.CharField(max_length=11, unique=True, validators=[phone_regex], blank=False)
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, blank=False)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, blank=False)
    is_verified = models.BooleanField(default=False)

    # Preferences / state for the top bar
    THEME_CHOICES = [('light', 'Light'), ('dark', 'Dark')]
    theme = models.CharField(max_length=5, choices=THEME_CHOICES, default='light')   # dark mode switch
    notifications_seen_at = models.DateTimeField(null=True, blank=True)              # last time the bell was opened
    notifications_cleared_at = models.DateTimeField(null=True, blank=True)           # "Clear all": older ones are hidden

    # Suspended by an admin (core_admin): is_active is False, so they can't log in,
    # and a suspended landlord's listings are hidden from renters
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True)

    # Consent at sign-up (step 5): which Terms / Privacy Notice they agreed to, and when
    terms_version = models.CharField(max_length=20, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)

    # Account pop-up (core_accounts/account.py)
    # Profile photo; without one, the avatar is the initials on blue (landlords) / yellow (renters)
    avatar = models.ImageField(upload_to=avatar_path, blank=True)
    # Contact sharing: renters -> landlords they apply to; landlords -> renters on their listings.
    # Both off = talk through LookApt chat only (the default).
    share_email = models.BooleanField(default=False)
    share_phone = models.BooleanField(default=False)

# ----------------------------------------------------------- TRIGGER FOR USERNAMES
# ------------------------------- USERNAME FORMAT: firstname.lastname

    def save(self, *args, **kwargs):
        self.first_name = self.first_name.strip()
        self.last_name = self.last_name.strip()

        if not self.username:
            first_clean = re.sub(r'\s+', '', self.first_name).lower()
            last_clean = re.sub(r'\s+', '', self.last_name).lower()
            base_username = f"{first_clean}.{last_clean}"
            username = base_username

            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            self.username = username

        super().save(*args, **kwargs)



# ----------------------------- DISPLAY NAME: Firstname Lastname (property to be called)
    @property
    def display_name(self):
        return f"{self.first_name.title()} {self.last_name.title()}"

    @property
    def initials(self):
        return f"{self.first_name[:1]}{self.last_name[:1]}".upper()

    @property
    def avatar_url(self):
        return self.avatar.url if self.avatar else ""

    @property
    def shared_contact(self):
        """What this user lets the other side see (Settings > Contact sharing): e.g. 'a@b.com · 0917…', or ''."""
        return " · ".join(value for value, shared in ((self.email, self.share_email), (self.phone_number, self.share_phone))
                          if shared and value)




    def __str__(self):
        return self.username



    class Meta:
        constraints = [
            CheckConstraint(
                condition=Q(phone_number__regex=r'^09\d{9}$'),
                name='valid_ph_number'
            )
        ]

        db_table='users'



# --------------------------------------------------------------------------------------------------------------- CLASS RENTER - FOR RENTERS TABLE

class Renter(models.Model):
    renter_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, db_column='user_id')

    class Meta:
        db_table= 'renters'


# --------------------------------------------------------------------------------------------------------------- CLASS LANDLORD - FOR LANDLORDS TABLE

class Landlord(models.Model):
    landlord_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, db_column='user_id')

    class Meta:
        db_table= 'landlords'

