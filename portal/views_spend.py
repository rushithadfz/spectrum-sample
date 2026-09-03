"""
The manager's spend dashboard.

Everything on it is derived from data already in the portal - agents' payouts,
their monthly trend rows, approved plans - except channel-level figures, which
come from the wider business. It is also actionable: the manager sets the
budget and decides every flagged exception.
"""

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    Budget,
    Channel,
    IncentivePlan,
    PayoutException,
    RoleType,
)
from .views_team import _roster_rows, role_required

# Bands for the payout-distribution chart.
BANDS = [
    ("$0-500", 0, 500),
    ("$500-1k", 500, 1000),
    ("$1k-2k", 1000, 2000),
    ("$2k-3k", 2000, 3000),
    ("$3k+", 3000, None),
]


class BudgetForm(forms.Form):
    amount = forms.DecimalField(
        min_value=0, max_digits=12, decimal_places=2, label="Budget for this period",
        widget=forms.NumberInput(attrs={"step": "1000", "placeholder": "e.g. 250000"}),
    )


def _spend_figures(agents):
    """
    What has actually been committed to these agents this period.

    Commission plus SPIFF from each agent's current snapshot - the same numbers
    the agents see on their own home page, so the two never disagree.
    """
    committed = Decimal("0.00")
    units = 0
    payouts = []
    for a in agents:
        snap = a.snapshots.filter(is_current=True).first()
        if not snap:
            continue
        committed += snap.gross_commission + snap.spiff_earned
        units += snap.units_sold
        payouts.append(snap.pending_payout)
    return committed, units, payouts


def _distribution(payouts):
    """How many agents sit in each payout band."""
    rows = []
    for label, low, high in BANDS:
        count = sum(
            1 for p in payouts
            if p >= low and (high is None or p < high)
        )
        rows.append({"label": label, "count": count})
    peak = max([r["count"] for r in rows], default=1) or 1
    for r in rows:
        r["pct"] = round(r["count"] / peak * 100)
    return rows


def _trend(agents, monthly_budget):
    """
    Spend per month, aggregated across the agents' own trend rows, against the
    monthly slice of the budget.
    """
    totals = {}
    order = {}
    for a in agents:
        for point in a.trend.all():
            totals[point.month] = totals.get(point.month, Decimal("0")) + point.amount
            order.setdefault(point.month, point.order)

    months = sorted(totals, key=lambda m: order[m])
    peak = max(list(totals.values()) + [monthly_budget], default=Decimal("1")) or Decimal("1")
    return [
        {
            "month": m,
            "spend": totals[m],
            "spend_pct": round(totals[m] / peak * 100),
            "budget_pct": round(monthly_budget / peak * 100) if peak else 0,
            "over": totals[m] > monthly_budget,
        }
        for m in months
    ]


@role_required(RoleType.MANAGER)
def spend(request):
    agent = request.user.agent
    teams = list(agent.visible_teams.select_related("lead__user"))
    # The team's region is the key channels, trends and budgets are filed
    # under. agent.market is a free-text label ("Dallas / Fort Worth - TX")
    # and does not match, so it is only a fallback.
    region = (teams[0].region if teams else "") or agent.market
    people = list(agent.visible_agents)

    budget_row, _ = Budget.objects.get_or_create(
        region=region, period="August 2026",
        defaults={"amount": Decimal("250000.00")},
    )

    # ---- actions -----------------------------------------------------
    if request.method == "POST":
        if request.POST.get("set_budget"):
            form = BudgetForm(request.POST)
            if form.is_valid():
                budget_row.amount = form.cleaned_data["amount"]
                budget_row.set_by = agent
                budget_row.save()
                messages.success(request, "Budget updated.")
                return redirect("portal:spend")
        else:
            decision = request.POST.get("decide")
            if decision in ("clear", "escalate"):
                flagged = get_object_or_404(PayoutException, pk=request.POST.get("exception"))
                if not flagged.can_be_decided_by(agent):
                    raise PermissionDenied("That exception is not yours to decide.")
                flagged.status = (PayoutException.State.CLEARED if decision == "clear"
                                  else PayoutException.State.ESCALATED)
                flagged.decided_by = agent
                flagged.decision_note = request.POST.get("note", "").strip()
                flagged.save(update_fields=["status", "decided_by", "decision_note"])
                messages.success(
                    request,
                    f"{flagged.kind} for {flagged.agent.full_name} "
                    f"{'cleared' if decision == 'clear' else 'escalated'}.",
                )
                return redirect("portal:spend")
    else:
        form = BudgetForm(initial={"amount": budget_row.amount})

    if request.method == "POST":
        form = BudgetForm(initial={"amount": budget_row.amount})

    # ---- derived figures --------------------------------------------
    committed, units, payouts = _spend_figures(people)
    approved_plans = IncentivePlan.objects.filter(
        team__in=teams, status=IncentivePlan.State.APPROVED)
    plan_commitment = sum((p.estimated_cost for p in approved_plans), Decimal("0.00"))

    total_spend = committed + plan_commitment
    budget = budget_row.amount or Decimal("1")
    utilisation = round(total_spend / budget * 100) if budget else 0
    headcount = len(people)

    exceptions = list(
        PayoutException.objects.filter(agent__team__in=teams)
        .select_related("agent__user", "agent__team", "decided_by__user")
    )
    pending = [e for e in exceptions if e.is_pending]
    held = sum((e.amount for e in pending), Decimal("0.00"))

    rows = _roster_rows(people)
    attainments = [t.attainment for t in teams]

    return render(request, "portal/spend.html", {
        "region": region,
        "budget_row": budget_row,
        "budget_form": form,
        "budget": budget,
        "total_spend": total_spend,
        "committed": committed,
        "plan_commitment": plan_commitment,
        "approved_plans": approved_plans,
        "utilisation": utilisation,
        "remaining": budget - total_spend,
        "over_budget": total_spend > budget,
        "headcount": headcount,
        "avg_payout": (total_spend / headcount) if headcount else Decimal("0"),
        "cost_per_unit": (total_spend / units) if units else Decimal("0"),
        "units": units,
        "avg_attainment": round(sum(attainments) / len(attainments)) if attainments else 0,
        "trend": _trend(people, budget / Decimal("6")),
        "distribution": _distribution(payouts),
        "channels": Channel.objects.filter(region=region),
        "exceptions": exceptions,
        "pending": pending,
        "held": held,
        "top": rows[0] if rows else None,
        "active_nav": "spend",
    })
