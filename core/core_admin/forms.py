from django import forms

from core.models import User


class UserEditForm(forms.ModelForm):
    """Admin panel → user profile → Edit details."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone_number"]

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another account already uses this email.")
        return email