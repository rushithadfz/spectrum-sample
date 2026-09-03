"""
The agent directory.

The team page answers "how is my squad doing"; this answers "find me a
person". Different question, so it is a different page: everyone the viewer
can see, searchable, filterable by team, sortable, and paged.

Scope is never a URL parameter - it comes from the viewer's own role, so a
lead cannot page their way into another lead's squad.
"""

from decimal import Decimal

from django.core.paginator import Paginator
from django.shortcuts import render

from .models import RoleType
from .views_team import role_required

PER_PAGE = 8

SORTS = {
    "name":       ("full_name", "Agent"),
    "team":       ("team", "Team"),
    "units":      ("units", "Units"),
    "payout":     ("payout", "Variable pay"),
    "attainment": ("attainment", "Attainment"),
}


def _row(a):
    snap = a.snapshots.filter(is_current=True).first()
    payout = (snap.gross_commission + snap.spiff_earned) if snap else Decimal("0.00")
    return {
        "agent": a,
        "full_name": a.full_name,
        "team": a.team.name if a.team else "",
        "market": a.market,
        "units": snap.units_sold if snap else 0,
        "payout": payout,
        "attainment": a.attainment,
        "attainment_class": a.attainment_class,
    }


@role_required(RoleType.LEAD, RoleType.MANAGER)
def directory(request):
    viewer = request.user.agent
    rows = [_row(a) for a in viewer.visible_agents]

    # ---- filter by team -------------------------------------------------
    teams = sorted({r["team"] for r in rows if r["team"]})
    team = request.GET.get("team", "").strip()
    if team and team in teams:
        rows = [r for r in rows if r["team"] == team]

    # ---- free text ------------------------------------------------------
    query = request.GET.get("q", "").strip()
    if query:
        needle = query.lower()
        rows = [r for r in rows
                if needle in r["full_name"].lower()
                or needle in r["team"].lower()
                or needle in r["market"].lower()]

    # ---- sort -----------------------------------------------------------
    sort = request.GET.get("sort", "attainment")
    if sort not in SORTS:
        sort = "attainment"
    key = SORTS[sort][0]
    # Names read better ascending; every figure reads better with the
    # biggest at the top.
    descending = sort != "name"
    rows.sort(key=lambda r: r[key], reverse=descending)

    # ---- page -----------------------------------------------------------
    paginator = Paginator(rows, PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))

    # Keep the current filters on every pagination link.
    carried = []
    for field, value in (("q", query), ("team", team), ("sort", sort)):
        if value:
            carried.append(f"{field}={value}")
    querystring = ("&" + "&".join(carried)) if carried else ""

    return render(request, "portal/directory.html", {
        "page": page,
        "rows": page.object_list,
        "total": paginator.count,
        "teams": teams,
        "team": team,
        "query": query,
        "sort": sort,
        "sorts": SORTS,
        "querystring": querystring,
        "filtered": bool(query or team),
        "active_nav": "directory",
    })
