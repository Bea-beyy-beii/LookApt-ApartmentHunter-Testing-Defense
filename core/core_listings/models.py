# core_listings/models.py
import uuid
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q
from decimal import Decimal


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

    sex_restriction = models.CharField(max_length=12, choices=SexRestriction.choices, default=SexRestriction.NO_RESTRICTION)
    lease_term = models.CharField(max_length=10, choices=LeaseTerm.choices, default=LeaseTerm.MONTHLY)

    # Days the landlord needs between tenants (cleaning, repairs...).
    # Waitlist move-in = current lease end + this.
    turnover_days = models.PositiveSmallIntegerField(default=7, validators=[MaxValueValidator(90)])

    num_of_floors = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )

    pet_friendly = models.BooleanField(default=False)
    has_parking_space = models.BooleanField(default=False)
    is_gated = models.BooleanField(default=False)
    has_laundry_area = models.BooleanField(default=False)
    has_security = models.BooleanField(default=False)            # 24/7 security
    has_cctv = models.BooleanField(default=False)
    has_common_lounge = models.BooleanField(default=False)
    has_waste_collection = models.BooleanField(default=False)

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

    def admits(self, user):
        """Whether the renter's sex fits the landlord's restriction (Male only / Female only)."""
        required = {SexRestriction.MALE_ONLY: "male", SexRestriction.FEMALE_ONLY: "female"}.get(self.sex_restriction)
        return required is None or getattr(user, "sex", None) == required

        # Counted in Python from self.units.all(), so the listings page's
    # prefetch_related("units") answers them without extra queries.
    # An unpublished complex counts all its units as unpublished (see Unit.listed_availability).
    def _count_units(self, availability=None):
        if availability is None:
            return len(self.units.all())
        if self.status == self.ComplexStatus.UNPUBLISHED:
            return len(self.units.all()) if availability == Unit.Availability.UNPUBLISHED else 0
        return sum(1 for unit in self.units.all() if unit.availability == availability)

    @property
    def total_units(self):
        return self._count_units()

    @property
    def available_units(self):
        return self._count_units(Unit.Availability.AVAILABLE)

    @property
    def occupied_units(self):
        return self._count_units(Unit.Availability.OCCUPIED)

    @property
    def unpublished_units(self):
        return self._count_units(Unit.Availability.UNPUBLISHED)

    
    # Feature checkboxes shown on the card and in the form (order = display order)
    FEATURE_LABELS = {
        "pet_friendly": "Pet Friendly",
        "has_parking_space": "Parking Space",
        "is_gated": "Gated Complex",
        "has_laundry_area": "Laundry Area",
        "has_security": "24/7 Security",
        "has_cctv": "CCTV",
        "has_common_lounge": "Common Lounge",
        "has_waste_collection": "Waste Collection",
    }

    def feature_list(self):
        """Ticked features, e.g. [{"key": "pet_friendly", "label": "Pet Friendly"}]."""
        return [{"key": key, "label": label} for key, label in self.FEATURE_LABELS.items() if getattr(self, key)]




class Unit(models.Model):
    class Availability(models.TextChoices):
        AVAILABLE = "available", "Available"
        OCCUPIED = "occupied", "Occupied"
        UNPUBLISHED = "unpublished", "Unpublished"

    # Amenity checkboxes shown in the unit form (order = display order)
    AMENITY_FIELDS = [
        "air_conditioned", "wifi_ready", "own_bathroom", "has_kitchen_area",
        "has_balcony", "has_window_view", "own_electric_meter", "has_water_heater",
    ]


    unit_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complex = models.ForeignKey(Complex, on_delete=models.CASCADE, related_name="units")

    identifier = models.PositiveSmallIntegerField()

    bedroom_type = models.CharField(max_length=12, choices=BedroomType.choices)
    length_dimension = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    width_dimension = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    unit_area = models.DecimalField(max_digits=8, decimal_places=2, default=0, editable=False)  # Stored so renters can filter by size; always calculated in save(), never typed in
    furnish_level = models.CharField(max_length=15, choices=FurnishLevel.choices)
    max_occupant = models.PositiveSmallIntegerField()

    floor = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])

    # Amenities / features
    air_conditioned = models.BooleanField("Air Conditioned", default=False)  
    wifi_ready = models.BooleanField("Wi-Fi Ready", default=False)
    own_bathroom = models.BooleanField("Own Bathroom", default=False)
    has_kitchen_area = models.BooleanField("Kitchen Area", default=False)
    has_balcony = models.BooleanField("With Balcony", default=False)
    has_window_view = models.BooleanField("With Window View", default=False)
    own_electric_meter = models.BooleanField("Own Electric Meter", default=False)
    has_water_heater = models.BooleanField("Hot Shower / Water Heater", default=False)

    unit_description = models.TextField(blank=True)

    # pricing: price is always the MONTHLY rent; lease_term is the commitment length
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(1)])
    deposit_months = models.PositiveSmallIntegerField(default=0)
    advance_months = models.PositiveSmallIntegerField(default=0)

    # The unit's own status. While its complex is unpublished the unit is shown as
    # unpublished (listed_availability) but keeps this value, so publishing the
    # complex again brings each unit back as it was.

    availability = models.CharField(max_length=15, choices=Availability.choices, default=Availability.AVAILABLE)

    # When the current tenant's lease started (occupied units). Used for the
    # waitlist's earliest move-in date: start + lease term + turnover days.
    occupied_since = models.DateField(null=True, blank=True)

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

    @property
    def complex_unpublished(self):
        return self.complex.status == Complex.ComplexStatus.UNPUBLISHED

    @property
    def has_renter(self):
        """An active contract (Manage Rentals), current or starting soon: the unit can't be unpublished."""
        return self.tenancies.filter(status="active").exists()

    @property
    def listed_availability(self):
        """The status shown on the landlord's cards: unpublished while the complex is."""
        return self.Availability.UNPUBLISHED if self.complex_unpublished else self.availability

    def get_listed_availability_display(self):
        return self.Availability(self.listed_availability).label

    def amenity_list(self):
        """Ticked amenities, e.g. [{"key": "wifi_ready", "label": "Wi-Fi Ready"}]."""
        return [
            {"key": name, "label": self._meta.get_field(name).verbose_name}
            for name in self.AMENITY_FIELDS
            if getattr(self, name)
        ]

    def save(self, *args, **kwargs):
        if self.width_dimension is not None and self.length_dimension is not None:
            area = Decimal(str(self.width_dimension)) * Decimal(str(self.length_dimension))
            self.unit_area = area.quantize(Decimal("0.01"))
        super().save(*args, **kwargs)





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



class UnitVideo(models.Model):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="videos")
    video = models.FileField(upload_to="unit_videos/")
    position = models.PositiveSmallIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"{self.unit} – video {self.position + 1}"



# --------------------------------------------------------------------------------------------------------------- SAVED LISTINGS (renter bookmarks)

class SavedListing(models.Model):
    renter = models.ForeignKey("core.Renter", on_delete=models.CASCADE, related_name="saved_listings")
    complex = models.ForeignKey(Complex, on_delete=models.CASCADE, related_name="saved_by")
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-saved_at"]
        constraints = [
            models.UniqueConstraint(fields=["renter", "complex"], name="unique_saved_listing_per_renter")
        ]

    def __str__(self):
        return f"{self.renter.user} saved {self.complex}"


# --------------------------------------------------------------------------------------------------------------- LISTING VIEWS (landlord dashboard)

class ListingView(models.Model):
    """A renter opened a complex or unit page. At most one row per renter per
    page per day, so refreshing doesn't inflate the landlord's "Views"."""
    complex = models.ForeignKey(Complex, on_delete=models.CASCADE, related_name="views")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, null=True, blank=True, related_name="views")
    viewer = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="listing_views")
    viewed_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["complex", "viewed_on"])]

    def __str__(self):
        return f"{self.viewer} viewed {self.unit or self.complex} on {self.viewed_on}"