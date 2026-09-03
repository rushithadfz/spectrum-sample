"""
Team Lead and Manager views.

Access is by role, enforced server-side: a field agent cannot reach the team
pages by typing the URL, and a lead only ever sees their own squad.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from .models import Dispute, RoleType, Team


def role_required(*roles):
    """Allow only the given role types; anything else is a 403."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            agent = getattr(request.user, "agent", None)
            if agent is None or agent.role_type not in roles:
                raise PermissionDenied("Your role does not have access to this page.")
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def _roster_rows(agents):
    """Shared roster shaping for both the lead and manager views."""
    rows = []
    for a in agents:
        card = getattr(a, "scorecard", None)
        rows.append({
            "agent": a,
            "points": card.total_points if card else 0,
            "tier": card.current_tier.name if card and card.current_tier else "-",
            "rank": card.rank if card else 0,
            "attainment": a.attainment,
            "attainment_class": a.attainment_class,
            "open_disputes": a.disputes.filter(status__in=Dispute.OPEN_STATES).count(),
        })
    rows.sort(key=lambda r: r["attainment"], reverse=True)
    return rows


# --------------------------------------------------------------------------
@role_required(RoleType.LEAD, RoleType.MANAGER)
def team_view(request):
    """
    A lead's squad. A manager can switch between the teams they own via
    ?team_id=, but only to teams that are actually theirs.
    """
    agent = request.user.agent
    teams = list(agent.visible_teams)

    requested = request.GET.get("team_id")
    if requested:
        team = get_object_or_404(Team, pk=requested)
        if team not in teams:
            raise PermissionDenied("That team is not yours.")
    else:
        team = teams[0] if teams else None

    rows = _roster_rows(team.agents if team else [])
    on_track = [r for r in rows if r["attainment"] >= 100]

    return render(request, "portal/team.html", {
        "team": team,
        "teams": teams,
        "rows": rows,
        "on_track": len(on_track),
        "headcount": len(rows),
        "team_points": sum(r["points"] for r in rows),
        "open_disputes": sum(r["open_disputes"] for r in rows),
        "disputes": Dispute.objects.filter(
            agent__team=team, status__in=Dispute.OPEN_STATES
        ).select_related("agent__user") if team else [],
        "active_nav": "team",
    })


# --------------------------------------------------------------------------
@role_required(RoleType.MANAGER)
def market_view(request):
    """Every team the manager owns, plus a market-wide leaderboard."""
    agent = request.user.agent
    teams = list(agent.visible_teams.select_related("lead__user"))
    everyone = _roster_rows(agent.visible_agents)

    headcount = sum(t.headcount for t in teams)
    attainments = [t.attainment for t in teams]

    return render(request, "portal/market.html", {
        "teams": teams,
        "leaderboard": everyone[:10],
        "headcount": headcount,
        "team_count": len(teams),
        "avg_attainment": round(sum(attainments) / len(attainments)) if attainments else 0,
        "total_points": sum(r["points"] for r in everyone),
        "open_disputes": Dispute.objects.filter(
            agent__team__in=teams, status__in=Dispute.OPEN_STATES
        ).count(),
        "at_risk": [r for r in everyone if r["attainment"] < 70],
        "active_nav": "market",
    })
