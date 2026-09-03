"""Forms for the portal. Currently just raising a payout dispute."""

from django import forms

from .models import Dispute


class DisputeForm(forms.ModelForm):
    """
    Raise a dispute against a payout.

    The ticket number and the raising agent are set by the view, not the
    form, so neither can be spoofed from the browser.
    """

    class Meta:
        model = Dispute
        fields = ["subject", "category", "priority", "detail"]
        widgets = {
            "subject": forms.TextInput(attrs={
                "placeholder": "e.g. Accelerator bonus missing from August payout",
                "maxlength": 160,
            }),
            "detail": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Order numbers, dates and amounts help resolve this faster.",
            }),
        }
        labels = {
            "subject": "What is wrong?",
            "category": "Category",
            "priority": "Priority",
            "detail": "Details (optional)",
        }

    def clean_subject(self):
        subject = self.cleaned_data["subject"].strip()
        if len(subject) < 10:
            raise forms.ValidationError(
                "Give a bit more detail - at least 10 characters."
            )
        return subject
