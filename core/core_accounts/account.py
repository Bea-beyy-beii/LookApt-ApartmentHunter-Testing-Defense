"""
The Account pop-up (profile menu > My Profile / Settings), opened from every dashboard.

    Profile   save_avatar(), remove_avatar()   photo shown instead of the initials
    Settings  set_contact_sharing()            what the other side may see
              change_password()
"""
import io
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .services import AccountService

AVATAR_MAX_MB = 5
AVATAR_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
AVATAR_SIZE = 320          # stored as a 320x320 WEBP


def _square_webp(upload):
    """The uploaded photo, cropped to a centred square and shrunk, as WEBP bytes."""
    try:
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)          # phone photos taken sideways
        image = ImageOps.fit(image.convert("RGB"), (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    except (UnidentifiedImageError, OSError):
        raise ValidationError("That file isn't a photo we can read. Try a JPG, PNG or WEBP.")
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=85)
    return buffer.getvalue()


def save_avatar(user, upload):
    if not upload:
        raise ValidationError("Choose a photo first.")
    if Path(upload.name).suffix.lower() not in AVATAR_TYPES:
        raise ValidationError("Use a JPG, PNG or WEBP photo.")
    if upload.size > AVATAR_MAX_MB * 1024 * 1024:
        raise ValidationError(f"That photo is too big. The limit is {AVATAR_MAX_MB} MB.")
    data = _square_webp(upload)
    old = user.avatar.name if user.avatar else ""
    user.avatar.save("avatar.webp", ContentFile(data), save=False)
    user.save(update_fields=["avatar"])
    if old:
        user.avatar.storage.delete(old)


def remove_avatar(user):
    if user.avatar:
        user.avatar.delete(save=False)
        user.avatar = ""
        user.save(update_fields=["avatar"])


def set_contact_sharing(user, share_email, share_phone):
    user.share_email = bool(share_email)
    user.share_phone = bool(share_phone)
    user.save(update_fields=["share_email", "share_phone"])


def change_password(user, data):
    """Returns {field: error}; empty when the password was changed."""
    if not user.check_password(data.get("current_password") or ""):
        return {"current_password": "That's not your current password."}
    password, errors = AccountService.clean_new_password(user, data)      # same rules as sign-up
    if errors:
        return errors
    user.set_password(password)
    user.save(update_fields=["password"])
    return {}