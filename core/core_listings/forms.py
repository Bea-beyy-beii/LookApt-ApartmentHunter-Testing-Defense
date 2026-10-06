# core_listings/forms.py
import json
from botocore import args
from django import forms
from .models import Complex, Unit
import os
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from .icons import icon_svg


MAX_COMPLEX_PHOTOS = 5
MAX_PHOTO_SIZE_MB = 5
ALLOWED_PHOTO_EXTENSIONS = {".png", ".jpg", ".jpeg"}
ALLOWED_PHOTO_FORMATS = {"PNG", "JPEG"}   # what Pillow detects from the file content


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """ImageField that accepts several files and returns a list."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)] if data else []






MAX_UNIT_PHOTOS = 10

def validate_photo_uploads(photos, existing_count, max_count):
    """Shared by ComplexForm and UnitForm."""
    if existing_count + len(photos) > max_count:
        raise ValidationError(
            f"You can upload up to {max_count} photos ({existing_count} already saved)."
        )
    for photo in photos:
        extension = os.path.splitext(photo.name)[1].lower()
        detected = getattr(getattr(photo, "image", None), "format", None)
        if extension not in ALLOWED_PHOTO_EXTENSIONS or detected not in ALLOWED_PHOTO_FORMATS:
            raise ValidationError(f"{photo.name}: only PNG or JPG files are allowed.")
        if photo.size > MAX_PHOTO_SIZE_MB * 1024 * 1024:
            raise ValidationError(f"{photo.name} is larger than {MAX_PHOTO_SIZE_MB} MB.")
    return photos


MAX_UNIT_VIDEOS = 2
MAX_VIDEO_SIZE_MB = 50
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"}


class MultipleFileField(forms.FileField):
    """Like MultipleImageField, but for any file (used for videos)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)] if data else []


def _looks_like_video(upload):
    """Check the file's first bytes, not just its name (MP4/MOV have 'ftyp', WebM starts with 1A45DFA3)."""
    head = upload.read(12)
    upload.seek(0)
    return head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3"


def validate_video_uploads(videos, existing_count, max_count):
    if existing_count + len(videos) > max_count:
        raise ValidationError(
            f"You can upload up to {max_count} videos ({existing_count} already saved)."
        )
    for video in videos:
        extension = os.path.splitext(video.name)[1].lower()
        if extension not in ALLOWED_VIDEO_EXTENSIONS or not _looks_like_video(video):
            raise ValidationError(f"{video.name}: only MP4, WebM or MOV videos are allowed.")
        if video.size > MAX_VIDEO_SIZE_MB * 1024 * 1024:
            raise ValidationError(f"{video.name} is larger than {MAX_VIDEO_SIZE_MB} MB.")
    return videos


class ComplexForm(forms.ModelForm):

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

    def clean_photos(self):
        photos = self.cleaned_data.get("photos") or []
        existing = self.instance.pictures.count() if self.instance.pk else 0
        return validate_photo_uploads(photos, existing, MAX_COMPLEX_PHOTOS)

    
    
    FEATURE_FIELDS = ["pet_friendly", "has_parking_space", "is_gated", "has_laundry_area"]

    def feature_fields(self):
        return [{"field": self[name], "icon": icon_svg(name)} for name in self.FEATURE_FIELDS]


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
            "is_gated",
            "has_laundry_area",
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
        }

        labels = {
            "num_of_floors": "Number of Floors",
            "pet_friendly": "Pet Friendly",
            "has_parking_space": "Parking Space",
            "is_gated": "Gated Complex",
            "has_laundry_area": "Laundry Area",
            "advance_months": "Advance Payment (months)",
            "deposit_months": "Security Deposit (months)",
        }

    def __init__(self, *args, landlord=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Needed to check the name is unique (landlord isn't a form field)
        self.landlord = landlord or (self.instance.landlord if self.instance.landlord_id else None)

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
        raw = self.cleaned_data.get("landmarks_json") or "[]"
        try:
            landmarks = json.loads(raw)
        except ValueError:
            raise forms.ValidationError("Invalid landmarks data.")
        if not isinstance(landmarks, list):
            raise forms.ValidationError("Invalid landmarks data.")
        return [item for item in landmarks if isinstance(item, dict)]

    def clean(self):
        cleaned = super().clean()
        min_price, max_price = cleaned.get("min_price"), cleaned.get("max_price")
        if min_price and max_price and min_price > max_price:
            self.add_error("max_price", "Max price must be greater than or equal to min price.")
        return cleaned


class UnitForm(forms.ModelForm):

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
        return [{"field": self[name], "icon": icon_svg(name)} for name in Unit.AMENITY_FIELDS]

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

    def clean_photos(self):
        photos = self.cleaned_data.get("photos") or []
        existing = self.instance.pictures.count() if self.instance.pk else 0
        return validate_photo_uploads(photos, existing, MAX_UNIT_PHOTOS)

    def clean_videos(self):
        videos = self.cleaned_data.get("videos") or []
        existing = self.instance.videos.count() if self.instance.pk else 0
        return validate_video_uploads(videos, existing, MAX_UNIT_VIDEOS)

    def _clean_months(self, name):
            value = self.cleaned_data.get(name)
            if value is not None and value > 12:
                raise ValidationError("Maximum is 12 months.")
            return value
    
    def clean_advance_months(self):
        return self._clean_months("advance_months")

    def clean_deposit_months(self):
        return self._clean_months("deposit_months")
    