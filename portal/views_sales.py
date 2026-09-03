"""
Logging a sale, and signing off the incentive it earns.

One view, two faces - the same shape as disputes:

  agent  ->  logs a sale, which goes out AWAITING LEAD and earns nothing yet
  lead   ->  sees every sale their agents logged and approves or rejects it

A sale only pays once the agent's own team lead has approved it, so the
figure an agent sees as "earned" and the figure a lead signed off are always
the same number.
"""

import json
from datetime import date
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Offer, RoleType, Sale, Status
from .views_team import role_required


class SaleForm(forms.ModelForm):
    """What an agent fills in. Money is derived, never typed."""

    class Meta:
        model = Sale
        fields = ["offer", "customer", "units", "sold_on"]
        widgets = {
            "customer": forms.TextInput(attrs={"placeholder": "Customer name or account"}),
            "units": forms.NumberInput(attrs={"min": 1, "max": 20}),
            "sold_on": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "offer": "What did you sell?",
            "customer": "Customer",
            "units": "Units",
            "sold_on": "Date sold",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["offer"].queryset = Offer.objects.filter(status=Status.ACTIVE)
        self.fields["offer"].empty_label = "Choose an offer"
        self.fields["sold_on"].initial = date.today()
        self.fields["units"].initial = 1

    def clean_sold_on(self):
        sold_on = self.cleaned_data["sold_on"]
        if sold_on > date.today():
            raise forms.ValidationError("You cannot log a sale with a future date.")
        return sold_on

    def clean_units(self):
        units = self.cleaned_data["units"]
        if units < 1:
            raise forms.ValidationError("A sale needs at least one unit.")
        return units


def _next_order_no():
    """Order numbers are unique and human-quotable on a dispute."""
    last = Sale.objects.order_by("-pk").first()
    return f"ORD-{(last.pk if last else 0) + 1 + 880000}"


def _agent_page(request, agent):
    form = SaleForm()

    # An agent has no decision to make on their own sale. Refuse it outright
    # rather than silently re-rendering the page as if nothing happened.
    if request.method == "POST" and request.POST.get("decide"):
        raise PermissionDenied("Only your team lead can approve a sale.")

    if request.method == "POST" and request.POST.get("log_sale"):
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = form.save(commit=False)
            sale.agent = agent
            sale.order_no = _next_order_no()
            # Money comes off the offer, so an agent cannot inflate their own
            # incentive by editing a field.
            sale.base = form.cleaned_data["offer"].commission * sale.units
            sale.spiff = form.cleaned_data["offer"].spiff * sale.units
            sale.status = Sale.SaleStatus.PENDING
            sale.approval = Sale.Approval.AWAITING_LEAD
            sale.save()
            messages.success(
                request,
                f"{sale.order_no} logged. {sale.incentive_value:,.2f} is awaiting "
                f"{agent.team.lead.first_name if agent.team and agent.team.lead else 'your lead'}.",
            )
            return redirect("portal:sales")

    sales = list(agent.sales.select_related("offer", "decided_by__user"))
    approved = sum((s.earned for s in sales), Decimal("0.00"))
    pending = sum(
        (s.incentive_value for s in sales if s.is_awaiting_decision), Decimal("0.00")
    )
    # Rates for the live payout preview, so the agent sees what a sale is
    # worth before submitting. The server still recomputes on save - this is
    # a convenience, never the source of truth.
    rates = {
        str(o.pk): {
            "name": o.name,
            "commission": float(o.commission),
            "spiff": float(o.spiff),
        }
        for o in Offer.objects.filter(status=Status.ACTIVE)
    }

    return render(request, "portal/sales.html", {
        "is_queue": False,
        "form": form,
        "offer_rates": json.dumps(rates),
        "sales": sales,
        "approved_total": approved,
        "pending_total": pending,
        "awaiting_count": sum(1 for s in sales if s.is_awaiting_decision),
        "active_nav": "sales",
    })


def _lead_page(request, approver):
    if request.method == "POST" and request.POST.get("decide"):
        decision = request.POST.get("decide")
        sale = get_object_or_404(Sale, order_no=request.POST.get("order"))
        if not sale.can_be_decided_by(approver):
            raise PermissionDenied("That sale is not yours to approve.")
        if decision not in ("approve", "reject"):
            raise PermissionDenied("Unknown decision.")
        sale.approval = (Sale.Approval.APPROVED if decision == "approve"
                         else Sale.Approval.REJECTED)
        sale.decided_by = approver
        sale.decision_note = request.POST.get("note", "").strip()
        sale.decided_on = timezone.now()
        sale.save(update_fields=["approval", "decided_by", "decision_note", "decided_on"])
        messages.success(
            request,
            f"{sale.order_no} {'approved' if decision == 'approve' else 'rejected'} "
            f"for {sale.agent.full_name}.",
        )
        return redirect("portal:sales")

    people = list(approver.visible_agents)
    sales = list(
        Sale.objects.filter(agent__in=people)
        .select_related("agent__user", "agent__team", "offer", "decided_by__user")
    )
    awaiting = [s for s in sales if s.is_awaiting_decision]
    return render(request, "portal/sales.html", {
        "is_queue": True,
        "sales": sales,
        "awaiting": awaiting,
        "awaiting_count": len(awaiting),
        "pending_total": sum((s.incentive_value for s in awaiting), Decimal("0.00")),
        "approved_total": sum((s.earned for s in sales), Decimal("0.00")),
        "active_nav": "sales",
    })


@role_required(RoleType.AGENT, RoleType.LEAD, RoleType.MANAGER)
def sales(request):
    agent = request.user.agent
    if agent.is_agent:
        return _agent_page(request, agent)
    return _lead_page(request, agent)
