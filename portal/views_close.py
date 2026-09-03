"""
Month-end close.

Three steps, each with a rule the server enforces rather than the template
hiding a button:

  1. calculate  - freezes the period's figures. Refused while any payout
                  exception is still pending, because the total would be
                  wrong the moment one is cleared.
  2. approve    - hands the frozen total to payroll. Refused unless the
                  period has been calculated.
  3. locked     - once approved nothing may be recalculated or re-approved.

Only the manager who owns the region may do any of it.
"""

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import IncentivePlan, PayoutException, PeriodClose, RoleType, Sale
from .views_team import role_required

PERIOD = "August 2026"


def _figures(teams, people):
    """
    What this period actually owes, from three independent sources.

    Kept separate rather than summed early so the close screen can show
    where the money came from, and so a wrong total can be traced.
    """
    payouts = Decimal("0.00")
    for a in people:
        snap = a.snapshots.filter(is_current=True).first()
        if snap:
            payouts += snap.gross_commission + snap.spiff_earned

    plans = sum(
        (p.estimated_cost for p in IncentivePlan.objects.filter(
            team__in=teams, status=IncentivePlan.State.APPROVED)),
        Decimal("0.00"),
    )
    # Only sales a team lead signed off count towards payroll.
    sales = sum(
        (s.earned for s in Sale.objects.filter(agent__in=people)),
        Decimal("0.00"),
    )
    return payouts, plans, sales


@role_required(RoleType.MANAGER)
def close(request):
    manager = request.user.agent
    teams = list(manager.visible_teams)
    people = list(manager.visible_agents)
    region = (teams[0].region if teams else "") or manager.market

    period, _ = PeriodClose.objects.get_or_create(region=region, period=PERIOD)

    pending = list(
        PayoutException.objects.filter(
            agent__team__in=teams, status=PayoutException.State.PENDING
        ).select_related("agent__user", "agent__team")
    )

    if request.method == "POST":
        action = request.POST.get("action")

        if period.is_locked:
            raise PermissionDenied("This period is with payroll and cannot be changed.")

        if action == "calculate":
            if not period.can_calculate:
                raise PermissionDenied("This period cannot be calculated.")
            if pending:
                # Refused rather than silently excluded: a total that ignores
                # held money is worse than no total.
                messages.error(
                    request,
                    f"{len(pending)} exception(s) are still open. Clear them before "
                    f"calculating, or the total will change underneath you.",
                )
                return redirect("portal:close")

            payouts, plans, sales = _figures(teams, people)
            period.agent_payouts = payouts
            period.plan_commitments = plans
            period.approved_sales = sales
            period.headcount = len(people)
            period.status = PeriodClose.State.CALCULATED
            period.calculated_by = manager
            period.calculated_on = timezone.now()
            period.save()
            messages.success(request, f"Calculated. {period.total:,.2f} is ready for review.")
            return redirect("portal:close")

        if action == "approve":
            if not period.can_approve:
                raise PermissionDenied("Calculate the period before approving it.")
            period.status = PeriodClose.State.APPROVED
            period.approved_by = manager
            period.approved_on = timezone.now()
            period.note = request.POST.get("note", "").strip()
            period.save()
            messages.success(request, "Approved for payroll. The period is now locked.")
            return redirect("portal:close")

        raise PermissionDenied("Unknown action.")

    # A preview of what calculating would produce, so the manager can see the
    # number before committing to it.
    preview_payouts, preview_plans, preview_sales = _figures(teams, people)

    return render(request, "portal/close.html", {
        "period": period,
        "region": region,
        "pending": pending,
        "blocked": bool(pending),
        "preview_total": preview_payouts + preview_plans + preview_sales,
        "preview_payouts": preview_payouts,
        "preview_plans": preview_plans,
        "preview_sales": preview_sales,
        "headcount": len(people),
        "held": sum((e.amount for e in pending), Decimal("0.00")),
        "active_nav": "close",
    })
