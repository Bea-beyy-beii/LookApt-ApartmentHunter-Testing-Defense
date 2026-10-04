# core_listings/forms.py
import json
from django import forms
from .models import Complex
import os
from django.core.exceptions import ValidationError


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

        if existing + len(photos) > MAX_COMPLEX_PHOTOS:
            raise ValidationError(
                f"You can upload up to {MAX_COMPLEX_PHOTOS} photos "
                f"({existing} already saved)."
            )

        for photo in photos:
            extension = os.path.splitext(photo.name)[1].lower()
            detected = getattr(getattr(photo, "image", None), "format", None)

            if extension not in ALLOWED_PHOTO_EXTENSIONS or detected not in ALLOWED_PHOTO_FORMATS:
                raise ValidationError(f"{photo.name}: only PNG or JPG files are allowed.")

            if photo.size > MAX_PHOTO_SIZE_MB * 1024 * 1024:
                raise ValidationError(f"{photo.name} is larger than {MAX_PHOTO_SIZE_MB} MB.")

        return photos

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
                    "step": "0.01"
                }
            ),

            "max_price": forms.NumberInput(
                attrs={
                    "placeholder": "0",
                    "min": "1",
                    "step": "0.01"
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A property must be pinned on the map
        self.fields["latitude"].required = True
        self.fields["longitude"].required = True
        self.fields["latitude"].error_messages["required"] = "Pin the property's location on the map."
        self.fields["longitude"].error_messages["required"] = "Pin the property's location on the map."

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
