import uuid
import re
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db.models import CheckConstraint, Q

from .roles import RoleBased

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
            self.username = self._unique_username()
        super().save(*args, **kwargs)

    def _unique_username(self):
        """firstname.lastname, with a number added if someone has it already."""
        first_clean = re.sub(r'\s+', '', self.first_name).lower()
        last_clean = re.sub(r'\s+', '', self.last_name).lower()
        base_username = f"{first_clean}.{last_clean}"
        username = base_username

        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        return username



# ----------------------------- ROLE: the user's profile object (polymorphism, see Profile below)

    # Admins have no profile row; their home is the admin panel
    ADMIN_HOME = 'core_admin:overview'

    @property
    def profile(self):
        """The Renter or Landlord object for this account (None for admins).
        Code asks the profile instead of checking `user.role == ...`."""
        return getattr(self, self.role, None) if self.role in ('renter', 'landlord') else None

    @property
    def home_url_name(self):
        """Where this user lands after logging in (each profile class answers for itself)."""
        profile_class = Profile.for_role(self.role)
        return profile_class.HOME_URL_NAME if profile_class else self.ADMIN_HOME

    def create_profile(self):
        """Make the Renter / Landlord row that goes with a new account."""
        return Profile.for_role(self.role).objects.create(user=self)

    @property
    def is_landlord(self):
        return self.role == 'landlord'

    @property
    def is_renter(self):
        return self.role == 'renter'

    @property
    def is_admin_user(self):
        return self.role == 'admin'


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



# --------------------------------------------------------------------------------------------------------------- CLASS PROFILE - SHARED PARENT OF RENTER AND LANDLORD

class Profile(RoleBased, models.Model):
    """What every role profile has: one User, and a home page.

    Abstract (no table of its own): Renter and Landlord inherit the `user` link
    and these methods, and each one overrides ROLE / HOME_URL_NAME / role_label.
    """

    ROLE = None               # 'renter' / 'landlord' (set by each subclass)
    HOME_URL_NAME = None      # the dashboard this role logs in to

    user = models.OneToOneField(User, on_delete=models.CASCADE, db_column='user_id')

    class Meta:
        abstract = True

    # for_role("renter") -> Renter, for_role("admin") -> None: inherited from RoleBased

    @property
    def rating(self):
        """Stars from renters' reviews; only landlords are rated (Landlord overrides this)."""
        return None

    @property
    def role_label(self):
        return self.ROLE.title()

    @property
    def display_name(self):
        return self.user.display_name

    def __str__(self):
        return f"{self.role_label}: {self.user.display_name}"


# --------------------------------------------------------------------------------------------------------------- CLASS RENTER - FOR RENTERS TABLE

class Renter(Profile):
    ROLE = 'renter'
    HOME_URL_NAME = 'core_renters:dashboard'

    renter_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        db_table= 'renters'


# --------------------------------------------------------------------------------------------------------------- CLASS LANDLORD - FOR LANDLORDS TABLE

class Landlord(Profile):
    ROLE = 'landlord'
    HOME_URL_NAME = 'core_landlords:dashboard'

    landlord_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        db_table= 'landlords'

    @property
    def rating(self):
        """{"avg", "count"} of the Landlord stars renters gave (profile menu), or None before the first review."""
        from core.core_reviews.models import Review        # core_reviews loads after this app
        rating = Review.objects.for_landlord(self).summary("landlord")
        return rating if rating["count"] else None
