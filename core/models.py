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

    # Suspended by an admin (core_admin): is_active is False, so they can't log in,
    # and a suspended landlord's listings are hidden from renters
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True)

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

