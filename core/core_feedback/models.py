import uuid

from django.conf import settings
from django.db import models


class FeedbackQuerySet(models.QuerySet):

    def answers_to_continue(self):
        """How many said Yes / Maybe / No to "would you continue using LookApt?"."""
        counts = dict(self.values_list("continue_using").annotate(n=models.Count("pk")))
        return [{"value": value, "label": label, "count": counts.get(value, 0)}
                for value, label in Feedback.ContinueUsing.choices]


class Feedback(models.Model):
    """One tester's answers to the Feedback Form (profile menu > Feedback Form).
    Admins read them in the admin panel's Feedback tab."""

    class ContinueUsing(models.TextChoices):
        YES = "yes", "Yes"
        MAYBE = "maybe", "Maybe"
        NO = "no", "No"

    feedback_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feedback")
    role = models.CharField(max_length=10)          # renter / landlord when they answered
    enjoyed = models.TextField()
    challenges = models.TextField()
    suggestions = models.TextField()
    continue_using = models.CharField(max_length=5, choices=ContinueUsing.choices)
    other = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FeedbackQuerySet.as_manager()

    class Meta:
        db_table = "feedback"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Feedback from {self.user} ({self.created_at:%Y-%m-%d})"
