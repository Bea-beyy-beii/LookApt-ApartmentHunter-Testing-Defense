import json

from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from . import services
from .models import VerificationRequest

Status = VerificationRequest.Status


class ReviewForm(forms.ModelForm):
    class Meta:
        model = VerificationRequest
        fields = ["status", "message"]
        labels = {"message": "Message to the landlord"}
        help_texts = {"message": "Required when asking for new documents or rejecting. The landlord sees it on their dashboard."}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") in (Status.RESUBMIT, Status.REJECTED) and not cleaned.get("message", "").strip():
            self.add_error("message", "Tell the landlord what to fix, or why they were rejected.")
        return cleaned


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    """Admins open a request, look at the documents and Claude's notes, then change
    the status (approved / new documents needed / rejected) and save."""

    form = ReviewForm
    list_display = ("landlord_name", "status", "id_type", "ownership_type", "created_at", "reviewed_by")
    list_filter = ("status", "id_type", "ownership_type")
    search_fields = ("landlord__user__first_name", "landlord__user__last_name", "landlord__user__email")
    actions = ["approve_selected"]
    readonly_fields = ("landlord_details", "id_type", "id_photo_preview", "selfie_preview", "ownership_type",
                       "ownership_document_preview", "ai_summary", "ai_details", "created_at", "reviewed_by",
                       "decided_at")
    fieldsets = (
        ("Landlord", {"fields": ("landlord_details", "created_at")}),
        ("Documents", {"fields": ("id_type", "id_photo_preview", "selfie_preview",
                                  "ownership_type", "ownership_document_preview")}),
        ("Automatic check (Claude)", {"fields": ("ai_summary", "ai_details")}),
        ("Decision", {"fields": ("status", "message", "reviewed_by", "decided_at")}),
    )

    def has_add_permission(self, request):
        return False           # only landlords submit documents

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("landlord__user", "reviewed_by")

    @admin.display(description="Landlord", ordering="landlord__user__last_name")
    def landlord_name(self, obj):
        return obj.landlord.user.display_name

    @admin.display(description="Account")
    def landlord_details(self, obj):
        user = obj.landlord.user
        return format_html("{}<br>{} · {}<br>Signed up {}", user.display_name, user.email or "no email",
                           user.phone_number, user.date_joined.strftime("%b %d, %Y"))

    def _preview(self, field_file):
        if not field_file:
            return "-"
        url = field_file.url          # signed link, valid for 5 minutes
        if field_file.name.lower().endswith(".pdf"):
            return format_html('<a href="{}" target="_blank" rel="noopener">Open PDF</a>', url)
        return format_html('<a href="{0}" target="_blank" rel="noopener">'
                           '<img src="{0}" alt="" style="max-width:420px;max-height:320px;border-radius:8px"></a>', url)

    @admin.display(description="Government ID")
    def id_photo_preview(self, obj):
        return self._preview(obj.id_photo)

    @admin.display(description="Selfie holding the ID")
    def selfie_preview(self, obj):
        return self._preview(obj.selfie)

    @admin.display(description="Permit / proof of ownership")
    def ownership_document_preview(self, obj):
        return self._preview(obj.ownership_document)

    @admin.display(description="What Claude read")
    def ai_details(self, obj):
        if not obj.ai_result:
            return "-"
        return format_html('<pre style="white-space:pre-wrap;max-width:720px">{}</pre>',
                           json.dumps(obj.ai_result, indent=2, ensure_ascii=False))

    def save_model(self, request, obj, form, change):
        if "status" not in form.changed_data:
            obj.save()
            return
        if obj.status == Status.APPROVED:
            services.approve(obj, request.user)
        elif obj.status == Status.RESUBMIT:
            services.ask_resubmit(obj, request.user, obj.message)
        elif obj.status == Status.REJECTED:
            services.reject(obj, request.user, obj.message)
        else:
            obj.save()

    @admin.action(description="Approve selected landlords")
    def approve_selected(self, request, queryset):
        count = 0
        for obj in queryset.select_related("landlord__user"):
            services.approve(obj, request.user)
            count += 1
        self.message_user(request, f"{count} landlord(s) approved.", messages.SUCCESS)