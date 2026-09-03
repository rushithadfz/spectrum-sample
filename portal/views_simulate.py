"""
Plan simulation.

Two scenarios, modelled side by side, before anything is committed. Nothing
here writes: the whole state lives in the query string, so a lead can send a
manager the exact comparison they were looking at.

Scope is taken from the viewer's own role, never from the URL - a lead can
only model their own teams.
"""

from decimal import Decimal, InvalidOperation

from django.shortcuts import redirect, render
from django.urls import reverse

from .models import Category, IncentivePlan, RoleType
from .simulation import Scenario, baseline_units, compare
from .views_team import role_required


def _decimal(raw, fallback=Decimal("0")):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return fallback
    return value if value >= 0 else fallback


def _int(raw, fallback=0):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return fallback
    return value if value >= 0 else fallback


def _scenario(request, side, teams, default_name, bump=0):
    """
    Read one scenario from the query string. Every field falls back to a
    sane default, so a bare /simulate/ still models something real.
    """
    def field(key, fallback=""):
        return request.GET.get(f"{side}_{key}", fallback)

    team_id = _int(field("team"), 0)
    team = next((t for t in teams if t.id == team_id), teams[0] if teams else None)

    category = field("category")
    if category not in dict(Category.choices):
        category = Category.choices[0][0]

    reward_type = field("reward")
    if reward_type not in dict(IncentivePlan.Reward.choices):
        reward_type = IncentivePlan.Reward.CASH

    # A default target under what the team already sells would open the page
    # on a warning about a plan nobody proposed. Start from real volume.
    default_units = int(baseline_units(team) * 1.15) or 120

    return Scenario(
        name=field("name") or default_name,
        team=team,
        category=category,
        reward_type=reward_type,
        reward_amount=_decimal(field("amount"), Decimal("25")),
        target_units=_int(field("units"), default_units + bump),
    )


@role_required(RoleType.LEAD, RoleType.MANAGER)
def simulate(request):
    agent = request.user.agent
    teams = list(agent.visible_teams)

    # Arriving from a plan seeds side A with that plan, so "what if we
    # changed this" starts from the real thing rather than a blank form.
    plan_id = _int(request.GET.get("plan"), 0)
    if plan_id and not request.GET.get("a_units"):
        plan = IncentivePlan.objects.filter(
            id=plan_id, team__in=teams,
        ).select_related("team").first()
        if plan:
            params = {
                "a_name": plan.name, "a_team": plan.team_id,
                "a_category": plan.category, "a_reward": plan.reward_type,
                "a_amount": plan.reward_amount, "a_units": plan.target_units,
                "b_name": f"{plan.name} (variant)", "b_team": plan.team_id,
                "b_category": plan.category, "b_reward": plan.reward_type,
                "b_amount": plan.reward_amount, "b_units": plan.target_units + 40,
            }
            query = "&".join(f"{k}={v}" for k, v in params.items())
            return redirect(f"{reverse('portal:simulate')}?{query}")

    a = _scenario(request, "a", teams, "Scenario A")
    b = _scenario(request, "b", teams, "Scenario B", bump=40)

    return render(request, "portal/simulate.html", {
        "result": compare(a, b),
        "teams": teams,
        "categories": Category.choices,
        "rewards": IncentivePlan.Reward.choices,
        "a": a, "b": b,
        "active_nav": "simulate",
    })
