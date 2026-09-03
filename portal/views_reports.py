"""
Reports.

Every report is built from live records at request time and is scoped to
what the person asking is allowed to see - a lead gets their own squad, a
manager gets every team they own. Nothing here is pre-baked or decorative:
the CSV a manager downloads is the same data the portal renders.

Adding a report means adding one builder to REPORTS. The hub, the preview
and the CSV endpoint all read from that registry, so the three can never
drift apart.
"""

import csv
from decimal import Decimal

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from .models import Dispute, PeriodClose, RoleType, Sale
from .views_team import role_required


# --------------------------------------------------------------------------
# Builders. Each returns (columns, rows) and takes the viewer's own agents.
# --------------------------------------------------------------------------

def _payout_register(agent, people, teams):
    cols = ["Agent", "Team", "Region", "Units sold", "Attainment %",
            "Commission", "SPIFF", "Total"]
    rows = []
    for a in sorted(people, key=lambda x: x.full_name):
        snap = a.snapshots.filter(is_current=True).first()
        if not snap:
            continue
        rows.append([
            a.full_name,
            a.team.name if a.team else "",
            a.team.region if a.team else "",
            snap.units_sold,
            a.attainment,
            f"{snap.gross_commission:.2f}",
            f"{snap.spiff_earned:.2f}",
            f"{snap.gross_commission + snap.spiff_earned:.2f}",
        ])
    return cols, rows


def _sales_ledger(agent, people, teams):
    cols = ["Order", "Date", "Agent", "Offer", "Customer", "Units",
            "Commission", "SPIFF", "Incentive", "Approval", "Decided by"]
    rows = []
    for s in (Sale.objects.filter(agent__in=people)
              .select_related("agent__user", "offer", "decided_by__user")
              .order_by("-sold_on")):
        rows.append([
            s.order_no, s.sold_on.isoformat(), s.agent.full_name, s.offer.name,
            s.customer, s.units, f"{s.base:.2f}", f"{s.spiff:.2f}",
            f"{s.incentive_value:.2f}", s.approval,
            s.decided_by.full_name if s.decided_by else "",
        ])
    return cols, rows


def _dispute_log(agent, people, teams):
    cols = ["Ticket", "Raised", "Agent", "Subject", "Category",
            "Priority", "Status", "Decided by", "Note"]
    rows = []
    for d in (Dispute.objects.filter(agent__in=people)
              .select_related("agent__user", "decided_by__user")
              .order_by("-raised_on")):
        rows.append([
            d.ticket_no, d.raised_on.isoformat(), d.agent.full_name, d.subject,
            d.category, d.priority, d.status,
            d.decided_by.full_name if d.decided_by else "",
            d.decision_note,
        ])
    return cols, rows


def _team_summary(agent, people, teams):
    cols = ["Team", "Region", "Lead", "Agents", "Attainment %", "Total payout"]
    rows = []
    for t in teams:
        members = list(t.agents.all())
        payout = Decimal("0.00")
        for m in members:
            snap = m.snapshots.filter(is_current=True).first()
            if snap:
                payout += snap.gross_commission + snap.spiff_earned
        rows.append([
            t.name, t.region, t.lead.full_name if t.lead else "",
            len(members), t.attainment, f"{payout:.2f}",
        ])
    return cols, rows


def _close_statement(agent, people, teams):
    """What was handed to payroll, and by whom."""
    cols = ["Region", "Period", "Status", "Agent payouts", "Approved sales",
            "Plan commitments", "Total", "Calculated by", "Approved by", "Note"]
    regions = {t.region for t in teams}
    rows = []
    for c in PeriodClose.objects.filter(region__in=regions):
        rows.append([
            c.region, c.period, c.status,
            f"{c.agent_payouts:.2f}", f"{c.approved_sales:.2f}",
            f"{c.plan_commitments:.2f}", f"{c.total:.2f}",
            c.calculated_by.full_name if c.calculated_by else "",
            c.approved_by.full_name if c.approved_by else "",
            c.note,
        ])
    return cols, rows


REPORTS = {
    "payout-register": {
        "name": "Payout register",
        "blurb": "Every agent's commission, SPIFF and total for the period.",
        "build": _payout_register,
    },
    "sales-ledger": {
        "name": "Sales ledger",
        "blurb": "Every logged sale with its approval state and who decided it.",
        "build": _sales_ledger,
    },
    "dispute-log": {
        "name": "Dispute log",
        "blurb": "All disputes raised, their outcome and the note sent back.",
        "build": _dispute_log,
    },
    "team-summary": {
        "name": "Team summary",
        "blurb": "Headcount, attainment and total payout per team.",
        "build": _team_summary,
    },
    "close-statement": {
        "name": "Close statement",
        "blurb": "The frozen figures handed to payroll, and who signed them off.",
        "build": _close_statement,
    },
}


def _scope(agent):
    """A lead sees their own squad; a manager sees every team they own."""
    return list(agent.visible_agents), list(agent.visible_teams)


def _build(slug, agent):
    spec = REPORTS.get(slug)
    if spec is None:
        raise Http404("No such report.")
    people, teams = _scope(agent)
    cols, rows = spec["build"](agent, people, teams)
    return spec, cols, rows


@role_required(RoleType.LEAD, RoleType.MANAGER)
def reports(request):
    agent = request.user.agent
    people, teams = _scope(agent)

    cards = []
    for slug, spec in REPORTS.items():
        _, _, rows = _build(slug, agent)
        cards.append({"slug": slug, "name": spec["name"],
                      "blurb": spec["blurb"], "count": len(rows)})

    return render(request, "portal/reports.html", {
        "cards": cards,
        "scope_agents": len(people),
        "scope_teams": len(teams),
        "generated": timezone.now(),
        "active_nav": "reports",
    })


@role_required(RoleType.LEAD, RoleType.MANAGER)
def report_detail(request, slug):
    spec, cols, rows = _build(slug, request.user.agent)
    return render(request, "portal/report_detail.html", {
        "slug": slug, "spec": spec, "cols": cols,
        "rows": rows[:200], "total_rows": len(rows),
        "truncated": len(rows) > 200,
        "generated": timezone.now(),
        "active_nav": "reports",
    })


@role_required(RoleType.LEAD, RoleType.MANAGER)
def report_csv(request, slug):
    spec, cols, rows = _build(slug, request.user.agent)
    stamp = timezone.now().strftime("%Y-%m-%d")
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{slug}-{stamp}.csv"'
    writer = csv.writer(resp)
    writer.writerow(cols)
    writer.writerows(rows)
    return resp


@role_required(RoleType.LEAD, RoleType.MANAGER)
def report_pdf(request, slug):
    """The same rows as the CSV and the on-screen table, laid out to print."""
    from .pdf import render_report

    agent = request.user.agent
    spec, cols, rows = _build(slug, agent)
    now = timezone.now()
    meta = (f"{agent.full_name} · {len(rows)} row(s) · "
            f"generated {now.strftime('%d %b %Y, %H:%M')}")

    resp = HttpResponse(
        render_report(cols, rows, spec["name"], spec["blurb"], meta),
        content_type="application/pdf",
    )
    resp["Content-Disposition"] = (
        f'attachment; filename="{slug}-{now.strftime("%Y-%m-%d")}.pdf"'
    )
    return resp
