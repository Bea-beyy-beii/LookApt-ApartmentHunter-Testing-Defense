from django import forms

from .models import Feedback


class FeedbackForm(forms.ModelForm):
    """The Feedback Form. The labels are the questions testers see."""

    QUESTIONS = {
        "enjoyed": "What features in LookApt did you enjoy the most or found the most useful? Why?",
        "challenges": "Did you encounter any challenges or issues in using the app? If there is, please elaborate.",
        "suggestions": "What are your suggestions to improve LookApt's functionalities and/or performance?",
        "continue_using": "As the pioneer testers of the application, would you consider to continue using this app after formal launch?",
        "other": "Any other concerns or suggestions:",
    }
    MAX_LENGTH = 3000

    class Meta:
        model = Feedback
        fields = ["enjoyed", "challenges", "suggestions", "continue_using", "other"]
        widgets = {"continue_using": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, question in self.QUESTIONS.items():
            field = self.fields[name]
            field.label = question
            if isinstance(field, forms.CharField):
                field.max_length = self.MAX_LENGTH
                field.strip = True
        self.fields["continue_using"].choices = Feedback.ContinueUsing.choices    # no empty "------" choice
        self.fields["continue_using"].error_messages["required"] = "Please choose an answer."
        for name in ("enjoyed", "challenges", "suggestions"):
            self.fields[name].error_messages["required"] = "Please answer this question."

    def save_for(self, user):
        feedback = self.save(commit=False)
        feedback.user = user
        feedback.role = user.role
        feedback.save()
        return feedback
