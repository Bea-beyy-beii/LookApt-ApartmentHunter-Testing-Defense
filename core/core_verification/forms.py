from pathlib import Path

from django import forms

from .models import VerificationRequest


class VerificationForm(forms.ModelForm):
    """The dashboard pop-up: an ID, a selfie holding it, and proof of ownership."""

    MAX_FILE_MB = 10
    PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
    PHOTO_KINDS = "a photo (JPG, PNG or WEBP)"

    # The first bytes of each file type, so a renamed .exe can't pass as a photo
    SIGNATURES = {
        ".jpg": lambda head: head[:3] == b"\xff\xd8\xff",
        ".jpeg": lambda head: head[:3] == b"\xff\xd8\xff",
        ".png": lambda head: head[:8] == b"\x89PNG\r\n\x1a\n",
        ".webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        ".pdf": lambda head: head[:5] == b"%PDF-",
    }

    class Meta:
        model = VerificationRequest
        fields = ["id_type", "id_photo", "selfie", "ownership_type", "ownership_document"]
        error_messages = {
            "id_type": {"required": "Choose the type of ID."},
            "id_photo": {"required": "Upload a photo of your ID."},
            "selfie": {"required": "Upload a selfie holding your ID."},
            "ownership_type": {"required": "Choose the type of document."},
            "ownership_document": {"required": "Upload your business permit or proof of ownership."},
        }

    def _check(self, upload, allowed, kinds):
        suffix = Path(upload.name).suffix.lower()
        if suffix not in allowed:
            raise forms.ValidationError(f"Please upload {kinds}.")
        if upload.size > self.MAX_FILE_MB * 1024 * 1024:
            raise forms.ValidationError(f"This file is larger than {self.MAX_FILE_MB} MB.")
        head = upload.read(12)
        upload.seek(0)
        if not self.SIGNATURES[suffix](head):
            raise forms.ValidationError(f"This file isn't a real {suffix[1:].upper()} file.")
        return upload

    def clean_id_photo(self):
        return self._check(self.cleaned_data["id_photo"], self.PHOTO_TYPES, self.PHOTO_KINDS)

    def clean_selfie(self):
        return self._check(self.cleaned_data["selfie"], self.PHOTO_TYPES, self.PHOTO_KINDS)

    def clean_ownership_document(self):
        return self._check(self.cleaned_data["ownership_document"], self.PHOTO_TYPES | {".pdf"},
                           "a photo (JPG, PNG, WEBP) or a PDF")
