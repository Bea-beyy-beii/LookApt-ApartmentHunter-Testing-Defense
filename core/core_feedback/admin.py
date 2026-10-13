from django.contrib import admin

from .models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "continue_using", "created_at")
    list_filter = ("role", "continue_using")
    search_fields = ("user__first_name", "user__last_name", "enjoyed", "challenges", "suggestions", "other")
