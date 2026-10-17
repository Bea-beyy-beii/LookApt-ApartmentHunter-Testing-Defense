# core_listings/models.py
import logging
import uuid
from django.conf import settings
from django.db import models, transaction
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal

logger = logging.getLogger(__name__)


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





class ListingChangeRefused(Exception):
    """A landlord asked for something the listing doesn't allow (e.g. unpublishing a rented unit).
    `status` is the JSON error code; `flash` = also show the error as a message."""

    def __init__(self, error, status=400, flash=True):
        super().__init__(error)
        self.error = error
        self.status = status
        self.flash = flash


class Listing(models.Model):
    """Parent of Complex and Unit (abstraction + polymorphism): the landlord's
    menu deletes or (un)publishes either one the same way, each subclass fills
    in its own name, renter check, files and status."""

    DELETE_REFUSED = ""         # set by the subclasses, "{name} ... can't be deleted"
    UNPUBLISH_REFUSED = ""      # "{name} ... can't be unpublished"

    class Meta:
        abstract = True

    @property
    def listing_name(self):
        raise NotImplementedError

    @property
    def has_renter(self):
        raise NotImplementedError

    def media_files(self):
        """Every stored photo/video file of this listing."""
        raise NotImplementedError

    def apply_status_button(self, choice, may_publish=True):
        """Use the status of the Save button the landlord clicked (not saved yet)."""
        raise NotImplementedError

    def set_status(self, value, may_publish=True):
        """The menu's publish / unpublish; raises ListingChangeRefused."""
        raise NotImplementedError

    def status_payload(self):
        """The JSON the menu gets back after set_status()."""
        raise NotImplementedError

    def add_photos(self, photos):
        """Save uploaded photos in order; the first becomes cover if there isn't one yet."""
        has_cover = self.pictures.filter(is_cover=True).exists()
        start_position = self.pictures.count()

        for index, photo in enumerate(photos):
            # the model allows only one cover per listing
            self.pictures.create(image=photo, position=start_position + index,
                                 is_cover=(not has_cover and index == 0))

    @transaction.atomic
    def arrange_photos(self, ordered):
        """Save the photo layout from the edit form: `ordered` holds the kept saved
        pictures and the new uploads, in order (forms.PhotoLayout). Saved pictures
        left out are deleted with their files; the first photo is the cover."""
        kept = {item.pk for item in ordered if isinstance(item, models.Model)}
        removed = [picture for picture in self.pictures.all() if picture.pk not in kept]
        files = [picture.image for picture in removed]
        for picture in removed:
            picture.delete()

        self.pictures.update(is_cover=False)        # one cover per listing: clear it before moving it
        for position, item in enumerate(ordered):
            if isinstance(item, models.Model):
                item.position, item.is_cover = position, position == 0
                item.save(update_fields=["position", "is_cover"])
            else:
                self.pictures.create(image=item, position=position, is_cover=position == 0)
        transaction.on_commit(lambda: self._delete_files(files))      # only once the save is final

    def delete_with_media(self):
        """Delete the listing and its files. Refused while a renter has a contract
        (that would also wipe the contracts and payments)."""
        if self.has_renter:
            raise ListingChangeRefused(self.DELETE_REFUSED.format(name=self.listing_name))
        files = self.media_files()
        self.delete()       # cascades to units, pictures, videos, landmarks
        self._delete_files(files)

    @staticmethod
    def _delete_files(files):
        """Remove files from storage (S3). Deleting rows does NOT delete their files."""
        for file in files:
            try:
                file.delete(save=False)
            except Exception as error:
                # Don't block the delete, but don't hide the problem either
                logger.warning("Could not delete %s: %s", file.name, error)


class ComplexQuerySet(models.QuerySet):

    def owned_by(self, user):
        # a landlord can only touch their own complexes
        return self.filter(landlord__user=user)

    def renter_visible(self):
        """Complexes renters are allowed to see.

        TEMPORARY: while settings.LISTINGS_REQUIRE_APPROVAL is False, every
        active complex is shown right away (no admin approval yet).
        """
        # Suspended landlords' listings are hidden too (core_admin)
        complexes = self.filter(status=Complex.ComplexStatus.ACTIVE, landlord__user__is_active=True)
        if getattr(settings, "LISTINGS_REQUIRE_APPROVAL", True):
            complexes = complexes.filter(approval_status=Complex.Approval.APPROVED)
        return complexes


class Complex(Listing):
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

    objects = ComplexQuerySet.as_manager()

    UNPUBLISH_REFUSED = "{name} has units with renters, so it can't be unpublished. End their contracts in Manage Rentals first."
    DELETE_REFUSED = "{name} has units with renters, so it can't be deleted. End their contracts in Manage Rentals first."
    NOT_VERIFIED = "Verify your account first: listings can be published once you're approved."

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

    @property
    def listing_name(self):
        return self.complex_name

    @property
    def has_renter(self):
        """Some unit has an active contract (Manage Rentals)."""
        return self.units.filter(tenancies__status="active").exists()

    def media_files(self):
        files = [picture.image for picture in self.pictures.all()]
        files += [picture.image for picture in UnitPicture.objects.filter(unit__complex=self)]
        files += [clip.video for clip in UnitVideo.objects.filter(unit__complex=self)]
        return files

    def apply_status_button(self, choice, may_publish=True):
        # "unpublished" or "active"; landlords who aren't verified yet can only save it unpublished
        if choice == self.ComplexStatus.ACTIVE and not may_publish:
            choice = self.ComplexStatus.UNPUBLISHED
        if choice in self.ComplexStatus.values:
            self.status = choice

    def set_status(self, visibility, may_publish=True):
        if visibility not in self.ComplexStatus.values:
            raise ListingChangeRefused("Invalid visibility.", flash=False)
        if visibility == self.ComplexStatus.ACTIVE and not may_publish:
            raise ListingChangeRefused(self.NOT_VERIFIED, status=403)
        if visibility == self.ComplexStatus.UNPUBLISHED and self.has_renter:
            raise ListingChangeRefused(self.UNPUBLISH_REFUSED.format(name=self.complex_name))
        self.status = visibility
        self.save(update_fields=["status", "updated_at"])

    def status_payload(self):
        return {
            "status": self.status,
            "label": self.get_status_display(),
            "approval_status": self.approval_status,
        }

    @property
    def next_unit_identifier(self):
        """Suggested first number for Bulk listing: one after the highest unit number."""
        highest = self.units.order_by("-identifier").values_list("identifier", flat=True).first()
        return (highest or 0) + 1

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

    def feature_checklist(self):
        """Every feature, ticked or not, e.g. for the amenities tab."""
        return [
            {"key": key, "label": label, "has": getattr(self, key)}
            for key, label in self.FEATURE_LABELS.items()
        ]




class UnitQuerySet(models.QuerySet):

    def owned_by(self, user):
        return self.filter(complex__landlord__user=user)

    def for_renters(self):
        # Renters never see unpublished units
        return (
            self.exclude(availability=Unit.Availability.UNPUBLISHED)
            .prefetch_related("pictures")
            .order_by("identifier")
        )


class Unit(Listing):
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

    objects = UnitQuerySet.as_manager()

    UNPUBLISH_REFUSED = "{name} has a renter, so it can't be unpublished. End the contract in Manage Rentals first."
    DELETE_REFUSED = "{name} has a renter, so it can't be deleted. End the contract in Manage Rentals first."
    COMPLEX_UNPUBLISHED = "This complex is unpublished. Publish it first to change its units' status."

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
    def listing_name(self):
        return self.unit_name

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

    def media_files(self):
        return [picture.image for picture in self.pictures.all()] + [clip.video for clip in self.videos.all()]

    def apply_status_button(self, choice, may_publish=True):
        # "available" (vacant), "occupied" or "unpublished".
        # A unit with a renter stays occupied (UnitForm already refuses unpublishing it).
        if not self._state.adding and self.has_renter:
            self.availability = self.Availability.OCCUPIED
        elif choice in self.Availability.values:
            self.availability = choice

    def set_status(self, availability, may_publish=True):
        if availability not in self.Availability.values:
            raise ListingChangeRefused("Invalid status.", flash=False)
        if self.complex_unpublished:
            raise ListingChangeRefused(self.COMPLEX_UNPUBLISHED)
        if availability == self.Availability.UNPUBLISHED and self.has_renter:
            raise ListingChangeRefused(self.UNPUBLISH_REFUSED.format(name=self.unit_name))

        # Occupied / available follow the contracts in Manage Rentals; the landlord
        # only publishes or unpublishes the unit
        if availability != self.Availability.UNPUBLISHED:
            availability = self.Availability.OCCUPIED if self.has_renter else self.Availability.AVAILABLE

        self.availability = availability
        self.save(update_fields=["availability", "updated_at"])

    def status_payload(self):
        return {"availability": self.availability, "label": self.get_availability_display()}

    def remove_videos(self, video_ids):
        """Delete these saved videos of this unit, with their files."""
        clips = list(self.videos.filter(pk__in=video_ids))
        files = [clip.video for clip in clips]
        self.videos.filter(pk__in=[clip.pk for clip in clips]).delete()
        transaction.on_commit(lambda: self._delete_files(files))

    def add_videos(self, videos):
        start = self.videos.count()
        for index, clip in enumerate(videos):
            self.videos.create(video=clip, position=start + index)

    def amenity_checklist(self):
        """Every amenity, ticked or not (the unit page)."""
        return [
            {"key": name, "label": self._meta.get_field(name).verbose_name, "has": getattr(self, name)}
            for name in self.AMENITY_FIELDS
        ]

    def payment_summary(self):
        advance = self.price * self.advance_months
        deposit = self.price * self.deposit_months
        return {
            "advance_months": self.advance_months,
            "advance": advance,
            "deposit_months": self.deposit_months,
            "deposit": deposit,
            # Move-in = advance + deposit; with neither, just the first month
            "total": (advance + deposit) or self.price,
        }

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
    is_manual = models.BooleanField(default=False)   # added by the landlord, not found on OpenStreetMap

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

    @classmethod
    def toggle(cls, renter, complex_obj):
        """Save the listing, or unsave it on the second click. True = now saved."""
        saved, created = cls.objects.get_or_create(renter=renter, complex=complex_obj)
        if not created:
            saved.delete()
        return created

    @classmethod
    def is_saved(cls, user, complex_obj):
        return cls.objects.filter(renter__user=user, complex=complex_obj).exists()


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

    @classmethod
    def record(cls, user, complex_obj, unit=None):
        """Count a renter's visit for the landlord's "Views" (once per page per day)."""
        cls.objects.get_or_create(complex=complex_obj, unit=unit, viewer=user, viewed_on=timezone.localdate())