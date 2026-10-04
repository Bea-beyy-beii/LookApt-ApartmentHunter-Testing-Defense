# core_listings/models.py
import uuid
from django.db import models
from django.core.validators import MinValueValidator
from django.db.models import Q


class SexRestriction(models.TextChoices):
    MALE_ONLY = "male_only", "Male only"
    FEMALE_ONLY = "female_only", "Female only"
    NO_RESTRICTION = "any", "Any"


class FurnishLevel(models.TextChoices):
    UNFURNISHED = "unfurnished", "Unfurnished"
    SEMI_FURNISHED = "semi_furnished", "Semi-furnished"
    FULLY_FURNISHED = "fully_furnished", "Fully furnished"


class BedroomType(models.TextChoices):
    STUDIO = "studio", "Studio"
    ONE = "one_bedroom", "Single bedroom"
    TWO = "two_bedroom", "2 bedrooms"
    THREE_PLUS = "three_plus", "3 or more"


class LeaseTerm(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly (3 months)"
    BIANNUAL = "biannual", "Biannual (6 months)"
    ANNUAL = "annual", "Annual (12 months)"





class Area(models.Model):
    area_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    area_name = models.TextField(unique=True)
    
    class Meta:
        ordering = ["area_name"]

    def __str__(self):
        return self.area_name





class Complex(models.Model):
    class ComplexStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        UNPUBLISHED = "unpublished", "Unpublished"

    class Approval(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    complex_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    landlord = models.ForeignKey("core.Landlord", on_delete=models.CASCADE, related_name="complexes")
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name="complexes")

    complex_name = models.TextField()
    address = models.TextField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    complex_description = models.TextField()
    pet_friendly = models.BooleanField(default=False)
    sex_restriction = models.CharField(max_length=12, choices=SexRestriction.choices, default=SexRestriction.NO_RESTRICTION)
    has_parking_space = models.BooleanField(default=False)
    lease_term = models.CharField(max_length=10, choices=LeaseTerm.choices, default=LeaseTerm.MONTHLY)
    min_price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(1)])
    max_price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(1)])

    status = models.CharField(max_length=12, choices=ComplexStatus.choices, default=ComplexStatus.UNPUBLISHED)
    approval_status = models.CharField(max_length=10, choices=Approval.choices, default=Approval.PENDING)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "complexes"
        constraints = [
            models.UniqueConstraint(
                fields=["landlord", "complex_name"], name="unique_complex_name_per_landlord"
            )
        ]

    def __str__(self):
        return self.complex_name

    @property
    def total_units(self):
        return self.units.count()

    @property
    def available_units(self):
        return self.units.filter(availability=Unit.Availability.AVAILABLE).count()

    @property
    def occupied_units(self):
        return self.units.filter(availability=Unit.Availability.OCCUPIED).count()





class Unit(models.Model):
    class Availability(models.TextChoices):
        AVAILABLE = "available", "Available"
        OCCUPIED = "occupied", "Occupied"
        UNPUBLISHED = "unpublished", "Unpublished"


    unit_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complex = models.ForeignKey(Complex, on_delete=models.CASCADE, related_name="units")

    identifier = models.PositiveSmallIntegerField()

    bedroom_type = models.CharField(max_length=12, choices=BedroomType.choices)
    length_dimension = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    width_dimension = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    air_conditioned = models.BooleanField(default=False)
    furnish_level = models.CharField(max_length=15, choices=FurnishLevel.choices)
    max_occupant = models.PositiveSmallIntegerField()
    unit_description = models.TextField(blank=True)

    # pricing: price is always the MONTHLY rent; lease_term is the commitment length
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(1)])
    deposit_months = models.PositiveSmallIntegerField(default=0)
    advance_months = models.PositiveSmallIntegerField(default=0)

    availability = models.CharField(max_length=15, choices=Availability.choices, default=Availability.AVAILABLE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["complex", "identifier"], name="unique_unit_identifier_per_complex")
        ]

    def __str__(self):
        return f"{self.complex} - Unit {self.identifier}"

    @property
    def unit_name(self):
            return f"Unit {self.identifier}"





class Landmark(models.Model): 

    class LandmarkTypes(models.TextChoices):
        SCHOOL = "school", "School"
        HEALTHCENTER = "healthcenter", "Hospital / Clinic"
        MARKET = "market", "Market"
        PHARMACY = "pharmacy", "Pharmacy / Drugstore"
        BANK = "bank", "Bank"
        RESTAURANT = "restaurant", "Restaurant / Eatery"
        TERMINAL = "terminal", "Transport Terminal"
        AIRPORT = "airport", "Airport"
        CHURCH = "church", "Church"
        GOVERNMENT = "government", "Government Office"
        MALL = "mall", "Mall"
        PARK = "park", "Park"
        GYM = "gym", "Gym"
        OTHER = "other", "Other"

    landmark_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    category = models.CharField(choices=LandmarkTypes.choices, max_length=25)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

class ComplexLandmark(models.Model):   # junction: complex <-> landmark, plus the estimate
    complex = models.ForeignKey(Complex, on_delete=models.CASCADE, related_name="landmarks")
    landmark = models.ForeignKey(Landmark, on_delete=models.CASCADE)
    distance_m = models.PositiveIntegerField()
    travel_minutes = models.PositiveSmallIntegerField()
    travel_mode = models.CharField(max_length=10, default="driving")  # or walking

    class Meta:
        unique_together = ("complex", "landmark", "travel_mode")






class ListingPicture(models.Model):
    is_cover = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)  # display order
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["position"]


class ComplexPicture(ListingPicture):
    complex = models.ForeignKey(Complex, on_delete=models.CASCADE, related_name="pictures")
    image = models.ImageField(upload_to="complex_pictures/")

    class Meta(ListingPicture.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["complex"], condition=Q(is_cover=True), name="one_cover_per_complex"
            )
        ]


class UnitPicture(ListingPicture):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="pictures")
    image = models.ImageField(upload_to="unit_pictures/")

    class Meta(ListingPicture.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["unit"], condition=Q(is_cover=True), name="one_cover_per_unit"
            )
        ]