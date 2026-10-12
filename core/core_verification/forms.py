from pathlib import Path

from django import forms

from .models import VerificationRequest

MAX_FILE_MB = 10
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}

# The first bytes of each file type, so a renamed .exe can't pass as a photo
_SIGNATURES = {
    ".jpg": lambda head: head[:3] == b"\xff\xd8\xff",
    ".jpeg": lambda head: head[:3] == b"\xff\xd8\xff",
    ".png": lambda head: head[:8] == b"\x89PNG\r\n\x1a\n",
    ".webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
    ".pdf": lambda head: head[:5] == b"%PDF-",
}


def _check(upload, allowed, kinds):
    suffix = Path(upload.name).suffix.lower()
    if suffix not in allowed:
        raise forms.ValidationError(f"Please upload {kinds}.")
    if upload.size > MAX_FILE_MB * 1024 * 1024:
        raise forms.ValidationError(f"This file is larger than {MAX_FILE_MB} MB.")
    head = upload.read(12)
    upload.seek(0)
    if not _SIGNATURES[suffix](head):
        raise forms.ValidationError(f"This file isn't a real {suffix[1:].upper()} file.")
    return upload


class VerificationForm(forms.ModelForm):
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

    def clean_id_photo(self):
        return _check(self.cleaned_data["id_photo"], PHOTO_TYPES, "a photo (JPG, PNG or WEBP)")

    def clean_selfie(self):
        return _check(self.cleaned_data["selfie"], PHOTO_TYPES, "a photo (JPG, PNG or WEBP)")

    def clean_ownership_document(self):
        return _check(self.cleaned_data["ownership_document"], PHOTO_TYPES | {".pdf"},
                      "a photo (JPG, PNG, WEBP) or a PDF")