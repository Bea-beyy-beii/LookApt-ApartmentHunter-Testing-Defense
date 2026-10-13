# core_listings/forms.py
import json
import os
from abc import ABC, abstractmethod

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import MaxLengthValidator
from django.db import transaction

from core.core_maps.maps.services import complex_landmarks, resolve_area, save_complex_landmarks

from .icons import Icon
from .models import Complex, Unit


# =========================================================
# UPLOAD FIELDS AND CHECKS
# =========================================================

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleUploadsMixin:
    """For a file field: accept several files and return a list (each one cleaned
    by the parent field's own clean())."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)] if data else []


class MultipleImageField(MultipleUploadsMixin, forms.ImageField):
    """ImageField that accepts several files and returns a list."""


class MultipleFileField(MultipleUploadsMixin, forms.FileField):
    """Like MultipleImageField, but for any file (used for videos)."""


class UploadCheck(ABC):
    """Checks a list of uploads against a limit (abstraction): PhotoCheck and
    VideoCheck only differ in which files are allowed."""

    NOUN = "files"
    MAX_SIZE_MB = 5
    WRONG_TYPE = "{name}: this file type isn't allowed."

    def __init__(self, existing_count, max_count):
        self.existing_count = existing_count
        self.max_count = max_count

    def validate(self, uploads):
        if self.existing_count + len(uploads) > self.max_count:
            raise ValidationError(
                f"You can upload up to {self.max_count} {self.NOUN} ({self.existing_count} already saved)."
            )
        for upload in uploads:
            if not self._allowed(upload):
                raise ValidationError(self.WRONG_TYPE.format(name=upload.name))
            if upload.size > self.MAX_SIZE_MB * 1024 * 1024:
                raise ValidationError(f"{upload.name} is larger than {self.MAX_SIZE_MB} MB.")
        return uploads

    @staticmethod
    def _extension(upload):
        return os.path.splitext(upload.name)[1].lower()

    @abstractmethod
    def _allowed(self, upload):
        """Whether the file is of an accepted type."""


class PhotoCheck(UploadCheck):
    NOUN = "photos"
    MAX_SIZE_MB = 5
    WRONG_TYPE = "{name}: only PNG or JPG files are allowed."
    EXTENSIONS = {".png", ".jpg", ".jpeg"}
    FORMATS = {"PNG", "JPEG"}          # what Pillow detects from the file content

    def _allowed(self, photo):
        detected = getattr(getattr(photo, "image", None), "format", None)
        return self._extension(photo) in self.EXTENSIONS and detected in self.FORMATS


class VideoCheck(UploadCheck):
    NOUN = "videos"
    MAX_SIZE_MB = 50
    WRONG_TYPE = "{name}: only MP4, WebM or MOV videos are allowed."
    EXTENSIONS = {".mp4", ".webm", ".mov"}

    def _allowed(self, video):
        return self._extension(video) in self.EXTENSIONS and self._looks_like_video(video)

    @staticmethod
    def _looks_like_video(upload):
        """Check the file's first bytes, not just its name (MP4/MOV have 'ftyp', WebM starts with 1A45DFA3)."""
        head = upload.read(12)
        upload.seek(0)
        return head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3"


class UploadCopies:
    """Uploaded files read once, so every unit of a bulk listing gets its own copy."""

    def __init__(self, uploads):
        self._files = []
        for upload in uploads:
            upload.seek(0)
            self._files.append((upload.name, upload.read()))

    def fresh(self):
        return [ContentFile(data, name=name) for name, data in self._files]


# =========================================================
# LISTING FORMS (the property and unit wizards)
# =========================================================

class ListingForm(forms.ModelForm):
    """Parent of ComplexForm and UnitForm (inheritance): the photo rules, the
    "can't unpublish while rented" check and the save_listing() /
    success_message() pair every wizard calls (polymorphism)."""

    MIN_PHOTOS = 2              # complexes and units: at least 2 photos (unit videos are optional)
    MAX_PHOTOS = None           # set by the subclasses
    PHOTO_NOUN = None           # "Add at least 2 photos of the ..."
    STATUS_BUTTON = None        # name of the clicked Save button's value
    UNPUBLISHED = "unpublished"

    @property
    def status_choice(self):
        return self.data.get(self.STATUS_BUTTON)

    def _icon_fields(self, names):
        return [{"field": self[name], "icon": Icon(name).svg()} for name in names]

    def clean_photos(self):
        photos = self.cleaned_data.get("photos") or []
        existing = self.instance.pictures.count() if self.instance.pk else 0
        if existing + len(photos) < self.MIN_PHOTOS:
            raise ValidationError(f"Add at least {self.MIN_PHOTOS} photos of the {self.PHOTO_NOUN}.")
        return PhotoCheck(existing, self.MAX_PHOTOS).validate(photos)

    def clean(self):
        cleaned = super().clean()
        self._clean_listing(cleaned)
        # "Save as Unpublished" on a listing with a renter
        if self.instance.pk and self.status_choice == self.UNPUBLISHED and self.instance.has_renter:
            self.add_error(None, self.instance.UNPUBLISH_REFUSED.format(name=self.instance.listing_name))
        return cleaned

    def _clean_listing(self, cleaned):
        """Extra checks of a subclass (runs before the renter check)."""

    def save_listing(self):
        raise NotImplementedError

    def success_message(self, saved):
        raise NotImplementedError


class ComplexForm(ListingForm):

    MAX_PHOTOS = 5
    PHOTO_NOUN = "property"
    STATUS_BUTTON = "visibility"

    # Filled by the map picker (core_maps) in step 2
    landmarks_json = forms.CharField(required=False, widget=forms.HiddenInput())

    photos = MultipleImageField(
            required=False,
                    widget=MultipleFileInput(attrs={
                        "accept": "image/png,image/jpeg",
                        "hidden": True,
                    }),
    )

    travel_mode = forms.CharField(required=False, widget=forms.HiddenInput())
    area_name = forms.CharField(required=False, widget=forms.HiddenInput())

    FEATURE_FIELDS = list(Complex.FEATURE_LABELS)      # the 8 Property Features checkboxes

    def feature_fields(self):
        return self._icon_fields(self.FEATURE_FIELDS)


    class Meta:
        model = Complex

        fields = [
            "complex_name",
            "complex_description",
            "address",
            "latitude",
            "longitude",
            "lease_term",
            "sex_restriction",
            "pet_friendly",
            "has_parking_space",
            "min_price",
            "max_price",
            "num_of_floors",
            "turnover_days",
            "is_gated",
            "has_laundry_area",
            "has_security",
            "has_cctv",
            "has_common_lounge",
            "has_waste_collection",
        ]

        widgets = {
            "complex_name": forms.TextInput(
                attrs={
                    "placeholder": "e.g. The Grand Residences"
                }
            ),

            "complex_description": forms.Textarea(
                attrs={
                    "placeholder": "Tell renters about your property...",
                    "rows": 4
                }
            ),

            "address": forms.TextInput(
                attrs={
                    "placeholder": "Drop a pin on the map to fill this in"
                }
            ),

            # Kept as hidden inputs; the map picker writes them
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),

            "lease_term": forms.Select(),

            "sex_restriction": forms.Select(),

            "pet_friendly": forms.CheckboxInput(),

            "has_parking_space": forms.CheckboxInput(),


            "min_price": forms.NumberInput(
                attrs={
                    "placeholder": "0",
                    "min": "1",
                    "max": "999999.99",
                    "step": "0.01"
                }
            ),

            "max_price": forms.NumberInput(
                attrs={
                    "placeholder": "0",
                    "min": "1",
                    "max": "999999.99",
                    "step": "0.01"
                }
            ),

            "num_of_floors": forms.NumberInput(attrs={"min": "1", "max": "100", "placeholder": "e.g. 3"}),
            "turnover_days": forms.NumberInput(attrs={"min": "0", "max": "90", "placeholder": "e.g. 7"}),
        }

        labels = {
            "num_of_floors": "Number of Floors",
            "turnover_days": "Turnover Period (days)",
            **Complex.FEATURE_LABELS,
            "advance_months": "Advance Payment (months)",
            "deposit_months": "Security Deposit (months)",
        }

    def __init__(self, *args, landlord=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Needed to check the name is unique (landlord isn't a form field)
        self.landlord = landlord or (self.instance.landlord if self.instance.landlord_id else None)
        self.creating = self.instance._state.adding
        self.publish_refused = False    # set by save_listing()

        # A property must be pinned on the map
        self.fields["latitude"].required = True
        self.fields["longitude"].required = True
        self.fields["latitude"].error_messages["required"] = "Pin the property's location on the map."
        self.fields["longitude"].error_messages["required"] = "Pin the property's location on the map."


    def clean_complex_name(self):
        # Without this, a repeated name crashed with an IntegrityError
        # (unique_complex_name_per_landlord) instead of showing an error
        name = self.cleaned_data["complex_name"].strip()
        if self.landlord:
            duplicates = Complex.objects.filter(landlord=self.landlord, complex_name__iexact=name)
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise ValidationError(f"You already have a property named \"{name}\".")
        return name



    def clean_landmarks_json(self):
        # Blank = the map never sent a list (still loading, or OpenStreetMap was
        # down): keep the saved landmarks instead of wiping them. "[]" = none.
        raw = self.cleaned_data.get("landmarks_json")
        if not raw:
            return None
        try:
            landmarks = json.loads(raw)
        except ValueError:
            raise forms.ValidationError("Invalid landmarks data.")
        if not isinstance(landmarks, list):
            raise forms.ValidationError("Invalid landmarks data.")
        return [item for item in landmarks if isinstance(item, dict)]

    def _clean_listing(self, cleaned):
        min_price, max_price = cleaned.get("min_price"), cleaned.get("max_price")
        if min_price and max_price and min_price > max_price:
            self.add_error("max_price", "Max price must be greater than or equal to min price.")

    # ---------- saving ----------

    @transaction.atomic
    def save_listing(self, may_publish=True):
        """Save the wizard form + the landmarks picked on the map (step 2).
        may_publish=False (landlord not verified yet) saves it unpublished."""
        complex_obj = self.save(commit=False)
        complex_obj.landlord = self.landlord
        moved = bool(complex_obj.pk) and {"latitude", "longitude"} & set(self.changed_data)

        self.publish_refused = self.status_choice == Complex.ComplexStatus.ACTIVE and not may_publish
        complex_obj.apply_status_button(self.status_choice, may_publish)

        area_name = self.cleaned_data.get("area_name")
        if area_name or not complex_obj.area_id:
            complex_obj.area = resolve_area(area_name)

        complex_obj.save()
        self._save_landmarks(complex_obj, moved)
        complex_obj.add_photos(self.cleaned_data.get("photos") or [])
        return complex_obj

    def _save_landmarks(self, complex_obj, moved):
        landmarks = self.cleaned_data.get("landmarks_json")
        travel_mode = self.cleaned_data.get("travel_mode")
        if landmarks is None and moved:
            # New pin but no new list: keep the landmarks, with distances from the new spot
            landmarks = saved = complex_landmarks(complex_obj)
            travel_mode = travel_mode or (saved[0]["travel_mode"] if saved else None)
        if landmarks is not None:
            save_complex_landmarks(complex_obj, landmarks, travel_mode)

    def success_message(self, saved):
        return f"{saved.complex_name} was {'created' if self.creating else 'saved'}."


class UnitForm(ListingForm):

    MAX_PHOTOS = 10
    MAX_VIDEOS = 2
    PHOTO_NOUN = "unit"
    STATUS_BUTTON = "availability"

    photos = MultipleImageField(
        required=False,
        widget=MultipleFileInput(attrs={"accept": "image/png,image/jpeg", "hidden": True}),
    )

    videos = MultipleFileField(
        required=False,
        widget=MultipleFileInput(attrs={"accept": "video/mp4,video/webm,video/quicktime", "hidden": True}),
    )

    class Meta:
        model = Unit
        fields = [
            "identifier", "floor", "bedroom_type",
            "width_dimension", "length_dimension",
            "max_occupant", "furnish_level", "price",
            "advance_months", "deposit_months",
            *Unit.AMENITY_FIELDS,
            "unit_description",
        ]
        labels = {
            "identifier": "Unit Number",
            "bedroom_type": "Unit Type",
            "width_dimension": "Width (m)",
            "length_dimension": "Length (m)",
            "max_occupant": "Max Occupants",
            "furnish_level": "Furnishing",
            "price": "Monthly Rent",
            "advance_months": "Advance Months",
            "deposit_months": "Deposit Months",
            "unit_description": "Additional Notes",
        }
        widgets = {
            "identifier": forms.NumberInput(attrs={"min": "1", "placeholder": "101"}),
            "floor": forms.NumberInput(attrs={"min": "1", "placeholder": "e.g. 1"}),
            "width_dimension": forms.NumberInput(attrs={"min": "0.5", "step": "0.01", "placeholder": "0"}),
            "length_dimension": forms.NumberInput(attrs={"min": "0.5", "step": "0.01", "placeholder": "0"}),
            "max_occupant": forms.NumberInput(attrs={"min": "1", "placeholder": "e.g. 2"}),
            "price": forms.NumberInput(attrs={"min": "1", "step": "0.01", "placeholder": "0"}),
            "unit_description": forms.Textarea(attrs={
                "rows": 3,
                "maxlength": "600",
                "placeholder": "e.g., special features, inclusions, or reminders for renters...",
            }),

            "advance_months": forms.NumberInput(attrs={"min": "0", "max": "12", "placeholder": "e.g. 1"}),

            "deposit_months": forms.NumberInput(attrs={"min": "0", "max": "12", "placeholder": "e.g. 2"}),
        }

    def __init__(self, *args, complex_obj, **kwargs):
        super().__init__(*args, **kwargs)
        self.complex = complex_obj

        # Browser-side limits (the clean_* methods below are the real check)
        self.fields["floor"].widget.attrs["max"] = complex_obj.num_of_floors
        self.fields["price"].widget.attrs["min"] = complex_obj.min_price
        self.fields["price"].widget.attrs["max"] = complex_obj.max_price
        self.fields["unit_description"].validators.append(MaxLengthValidator(600))

    def amenity_fields(self):
        return self._icon_fields(Unit.AMENITY_FIELDS)

    # ---------- validation ----------

    def clean_identifier(self):
        identifier = self.cleaned_data["identifier"]
        if identifier < 1:
            raise ValidationError("Unit number must be at least 1.")

        duplicates = Unit.objects.filter(complex=self.complex, identifier=identifier)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError(f"Unit {identifier} already exists in {self.complex.complex_name}.")
        return identifier

    def clean_floor(self):
        floor = self.cleaned_data.get("floor")
        if floor and floor > self.complex.num_of_floors:
            raise ValidationError(
                f"{self.complex.complex_name} only has {self.complex.num_of_floors} floor(s)."
            )
        return floor

    def _clean_dimension(self, name):
        value = self.cleaned_data.get(name)
        if value is not None and value <= 0:
            raise ValidationError("Must be greater than 0.")
        return value

    def clean_width_dimension(self):
        return self._clean_dimension("width_dimension")

    def clean_length_dimension(self):
        return self._clean_dimension("length_dimension")

    def clean_max_occupant(self):
        value = self.cleaned_data.get("max_occupant")
        if value is not None and value < 1:
            raise ValidationError("At least 1 occupant.")
        return value

    def clean_price(self):
        # Unit rent must be inside the complex's declared price range
        price = self.cleaned_data.get("price")
        low, high = self.complex.min_price, self.complex.max_price
        if price is not None and not (low <= price <= high):
            raise ValidationError(
                f"Monthly rent must be within this complex's price range (₱{low:,.0f} – ₱{high:,.0f})."
            )
        return price

    # clean_photos (videos are optional and don't count: a unit needs at least 2 photos) is ListingForm's

    def clean_videos(self):
        videos = self.cleaned_data.get("videos") or []
        existing = self.instance.videos.count() if self.instance.pk else 0
        return VideoCheck(existing, self.MAX_VIDEOS).validate(videos)

    def _clean_months(self, name):
        value = self.cleaned_data.get(name)
        if value is not None and value > 12:
            raise ValidationError("Maximum is 12 months.")
        return value

    def clean_advance_months(self):
        return self._clean_months("advance_months")

    def clean_deposit_months(self):
        return self._clean_months("deposit_months")

    # ---------- saving ----------

    @transaction.atomic
    def save_listing(self):
        unit = self.save(commit=False)
        unit.complex = self.complex
        unit.apply_status_button(self.status_choice)
        unit.save()
        unit.add_photos(self.cleaned_data.get("photos") or [])
        unit.add_videos(self.cleaned_data.get("videos") or [])
        return unit

    def success_message(self, saved):
        return f"Unit {saved.identifier} was saved."


# =========================================================
# ADD SEVERAL UNITS AT ONCE ("Bulk listing" switch on the Add Unit form)
# =========================================================

class BulkUnitForm(UnitForm):
    """The Add Unit form for several similar units: every UnitForm field and
    check is inherited (type, size, rent within the complex's range, photos ...);
    only the unit number is different. It is replaced by `unit_numbers`, e.g.
    "101, 102, 103", and each number becomes its own Unit with the same details."""

    MIN_UNITS = 2
    MAX_UNITS = 20

    unit_numbers = forms.CharField(label="Unit numbers", widget=forms.HiddenInput(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # One number per unit comes from unit_numbers instead
        self.fields["identifier"].required = False

    def clean_identifier(self):
        return None                      # overrides UnitForm's: not used here

    def clean_unit_numbers(self):
        raw = (self.cleaned_data.get("unit_numbers") or "").replace(" ", "")
        try:
            numbers = [int(part) for part in raw.split(",") if part]
        except ValueError:
            raise ValidationError("Unit numbers must be whole numbers.")

        if len(numbers) < self.MIN_UNITS:
            raise ValidationError(f"Add at least {self.MIN_UNITS} unit numbers (or turn off Bulk listing).")
        if len(numbers) > self.MAX_UNITS:
            raise ValidationError(f"You can add up to {self.MAX_UNITS} units at once.")
        if any(number < 1 for number in numbers):
            raise ValidationError("Unit numbers must be at least 1.")

        repeated = sorted({n for n in numbers if numbers.count(n) > 1})
        if repeated:
            raise ValidationError(f"Each unit needs its own number: {', '.join(map(str, repeated))} is used twice.")
        taken = sorted(Unit.objects.filter(complex=self.complex, identifier__in=numbers)
                       .values_list("identifier", flat=True))
        if taken:
            listed = ", ".join(f"Unit {n}" for n in taken)
            raise ValidationError(f"{listed} already exist{'s' if len(taken) == 1 else ''} in {self.complex.complex_name}.")
        return numbers

    def build_units(self):
        """One unsaved Unit per number, each a copy of the same details."""
        template = self.save(commit=False)
        units = []
        for number in self.cleaned_data["unit_numbers"]:
            unit = Unit(complex=self.complex)
            for field in self.Meta.fields:
                setattr(unit, field, getattr(template, field))
            unit.identifier = number
            units.append(unit)
        return units

    @transaction.atomic
    def save_listing(self):
        """Overrides UnitForm's: the same details, photos and videos for every unit number."""
        photos = UploadCopies(self.cleaned_data.get("photos") or [])
        videos = UploadCopies(self.cleaned_data.get("videos") or [])

        units = self.build_units()
        for unit in units:
            unit.apply_status_button(self.status_choice)
            unit.save()
            unit.add_photos(photos.fresh())
            unit.add_videos(videos.fresh())
        return units

    def success_message(self, saved):
        numbers = ", ".join(str(n) for n in sorted(u.identifier for u in saved))
        return f"{len(saved)} units were added: {numbers}."
