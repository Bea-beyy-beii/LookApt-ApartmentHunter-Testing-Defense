"""
The signed-in user's own account: the Account pop-up (profile menu > My Profile /
Settings) and the top bar, opened from every dashboard.

    account = Account(request.user)
    Profile   account.save_avatar(), remove_avatar()   photo shown instead of the initials
    Settings  account.set_contact_sharing()            what the other side may see
              account.change_password()
    Top bar   account.set_theme(), mark_notifications_seen(), clear_notifications()
"""
import io
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from .services import NewPasswordStep


class AvatarPhoto:
    """An uploaded profile photo: checked, then cropped to a centred square and shrunk."""

    MAX_MB = 5
    TYPES = {".jpg", ".jpeg", ".png", ".webp"}
    SIZE = 320          # stored as a 320x320 WEBP

    def __init__(self, upload):
        self.upload = upload

    def validate(self):
        if not self.upload:
            raise ValidationError("Choose a photo first.")
        if Path(self.upload.name).suffix.lower() not in self.TYPES:
            raise ValidationError("Use a JPG, PNG or WEBP photo.")
        if self.upload.size > self.MAX_MB * 1024 * 1024:
            raise ValidationError(f"That photo is too big. The limit is {self.MAX_MB} MB.")

    def webp_bytes(self):
        try:
            image = Image.open(self.upload)
            image = ImageOps.exif_transpose(image)          # phone photos taken sideways
            image = ImageOps.fit(image.convert("RGB"), (self.SIZE, self.SIZE), Image.LANCZOS)
        except (UnidentifiedImageError, OSError):
            raise ValidationError("That file isn't a photo we can read. Try a JPG, PNG or WEBP.")
        buffer = io.BytesIO()
        image.save(buffer, "WEBP", quality=85)
        return buffer.getvalue()


class Account:
    """What a user can change about their own account."""

    def __init__(self, user):
        self.user = user

    # ------------------------------------------------------------------ profile photo

    def save_avatar(self, upload):
        photo = AvatarPhoto(upload)
        photo.validate()
        data = photo.webp_bytes()
        user = self.user
        old = user.avatar.name if user.avatar else ""
        user.avatar.save("avatar.webp", ContentFile(data), save=False)
        user.save(update_fields=["avatar"])
        if old:
            user.avatar.storage.delete(old)

    def remove_avatar(self):
        user = self.user
        if user.avatar:
            user.avatar.delete(save=False)
            user.avatar = ""
            user.save(update_fields=["avatar"])

    @property
    def avatar_json(self):
        return {"url": self.user.avatar_url, "initials": self.user.initials}

    # ------------------------------------------------------------------ settings

    def set_contact_sharing(self, share_email, share_phone):
        self.user.share_email = bool(share_email)
        self.user.share_phone = bool(share_phone)
        self.user.save(update_fields=["share_email", "share_phone"])

    def change_password(self, data):
        """Returns {field: error}; empty when the password was changed."""
        if not self.user.check_password(data.get("current_password") or ""):
            return {"current_password": "That's not your current password."}
        step = NewPasswordStep(self.user, data)      # same rules as sign-up
        _, errors = step.clean()
        if errors:
            return errors
        self.user.set_password(step.password)
        self.user.save(update_fields=["password"])
        return {}

    # ------------------------------------------------------------------ top bar

    def set_theme(self, theme):
        """Dark mode switch: 'light' / 'dark'. False for anything else."""
        if theme not in dict(self.user.THEME_CHOICES):
            return False
        self.user.theme = theme
        self.user.save(update_fields=["theme"])
        return True

    def mark_notifications_seen(self):
        self.user.notifications_seen_at = timezone.now()
        self.user.save(update_fields=["notifications_seen_at"])

    def clear_notifications(self):
        """Hides everything so far; newer ones still show."""
        now = timezone.now()
        self.user.notifications_cleared_at = now
        self.user.notifications_seen_at = now
        self.user.save(update_fields=["notifications_cleared_at", "notifications_seen_at"])
