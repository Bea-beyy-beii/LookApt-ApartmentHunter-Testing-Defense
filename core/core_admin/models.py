import uuid

from django.conf import settings
from django.db import models


class Notice(models.Model):
    """A message from LookApt to one user, shown in their notification bell
    (verification results, report updates, warnings ...). See core_admin/notify.py."""

    class Tone(models.TextChoices):
        GREEN = "green", "Good news"
        YELLOW = "yellow", "Heads up"
        RED = "red", "Problem"

    notice_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notices")
    title = models.CharField(max_length=120)
    message = models.TextField()
    tone = models.CharField(max_length=10, choices=Tone.choices, default=Tone.GREEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notices"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} → {self.user}"