"""
The incentive-portal pages: Home, Incentives feed, Incentive detail,
Earnings Calculator, Disputes.

Structure and terminology follow the reference POC.
"""

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import DisputeForm
from .models import (
    Badge,
    Dispute,
    Incentive,
    Notification,
    Period,
    PointsRule,
    Quest,
    SavedPlan,
    Status,
    Tier,
)


def _agent(request):
    return getattr(request.user, "agent", None)


def _greeting(now=None):
    """Good morning / afternoon / evening, matching the POC's home header."""
    hour = (now or timezone.localtime()).hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


# --------------------------------------------------------------------------
@login_required
def home(request):
    """
    Home is a different page per role: a field agent lands on their own
    numbers, a lead on their squad, a manager on the market.
    """
    agent = _agent(request)
    if agent is not None and agent.is_lead:
        return _home_lead(request, agent)
    if agent is not None and agent.is_manager:
        return _home_manager(request, agent)
    return _home_agent(request, agent)


def _area_chart(trend, width=680, height=180, pad=14):
    """
    Turn the monthly trend into an SVG area chart.

    Six flat bars carried no shape; a line with a gradient fill under it shows
    the direction of the year at a glance. Geometry is computed here rather
    than in the template so the markup stays declarative.
    """
    if not trend:
        return None

    amounts = [float(t.amount) for t in trend]
    top, bottom = max(amounts), min(amounts)
    span = (top - bottom) or 1.0
    inner_h = height - pad * 2
    step = width / (len(trend) - 1) if len(trend) > 1 else width

    pts = []
    for i, t in enumerate(trend):
        x = round(i * step, 1)
        # Leave headroom so the peak never touches the top edge.
        y = round(pad + inner_h - ((float(t.amount) - bottom) / span) * inner_h * 0.86, 1)
        pts.append({"x": x, "y": y, "month": t.month, "amount": t.amount,
                    "is_last": i == len(trend) - 1})

    line = "M " + " L ".join(f"{p['x']},{p['y']}" for p in pts)
    area = f"{line} L {pts[-1]['x']},{height} L {pts[0]['x']},{height} Z"
    return {"line": line, "area": area, "points": pts,
            "width": width, "height": height,
            "peak": max(trend, key=lambda t: t.amount),
            "latest": trend[-1]}


def _tier_progress(agent):
    """
    Where this agent sits on the tier ladder and what the next rung is worth.

    Replaces the POC's virtual-world panel with something tied to the money:
    tiers are the part of a comp plan an agent can actually act on.
    """
    card = getattr(agent, "scorecard", None)
    if card is None:
        return None

    tiers = list(Tier.objects.all())
    if not tiers:
        return None

    points = card.total_points
    current = card.current_tier
    nxt = next((t for t in tiers if t.threshold_points > points), None)

    floor = current.threshold_points if current else 0
    if nxt:
        span = (nxt.threshold_points - floor) or 1
        pct = round(max(0, points - floor) / span * 100)
        uplift = nxt.payout - (current.payout if current else Decimal("0"))
    else:
        pct, uplift = 100, Decimal("0")

    return {
        "current": current,
        "next": nxt,
        "points": points,
        "pct": min(pct, 100),
        "to_go": max(nxt.threshold_points - points, 0) if nxt else 0,
        "uplift": uplift,
        "at_top": nxt is None,
        "ladder": tiers,
    }


def _next_action(agent, tier):
    """
    The single most useful thing this agent could do next.

    The home was showing about twenty figures and answering no question.
    This picks one directive, in priority order, and every branch is
    derived from real records - nothing is decorative.
    """
    from .models import Sale

    sales = list(agent.sales.all())

    rejected = [s for s in sales if s.approval == Sale.Approval.REJECTED]
    if rejected:
        return {"tone": "red", "label": "Needs attention",
                "text": f"{len(rejected)} sale(s) were rejected by your team lead.",
                "cta": "Review them", "url": reverse("portal:sales")}

    waiting = [s for s in sales if s.is_awaiting_decision]
    if waiting:
        held = sum((s.incentive_value for s in waiting), Decimal("0.00"))
        lead = agent.team.lead.first_name if agent.team and agent.team.lead else "your lead"
        return {"tone": "amber", "label": "Waiting on approval",
                "text": f"${held:,.0f} across {len(waiting)} sale(s) is with {lead}.",
                "cta": "See sales", "url": reverse("portal:sales")}

    open_disputes = [d for d in agent.disputes.all() if d.is_awaiting_decision]
    if open_disputes:
        return {"tone": "amber", "label": "Open dispute",
                "text": f"{len(open_disputes)} dispute(s) still awaiting a decision.",
                "cta": "Track them", "url": reverse("portal:disputes")}

    # Closest programme to finishing - the quickest money on the table.
    live = [i for i in Incentive.objects.exclude(bucket="previous") if i.goal]
    closest = None
    for i in live:
        left = i.goal - i.progress
        if left > 0 and (closest is None or left < closest[1]):
            closest = (i, left)
    if closest:
        prog, left = closest
        return {"tone": "blue", "label": "Closest to finishing",
                "text": f"{left} more {prog.unit} completes {prog.name}.",
                "cta": "Log a sale", "url": reverse("portal:sales")}

    if tier and not tier["at_top"]:
        return {"tone": "blue", "label": "Next tier",
                "text": f"{tier['to_go']} points to {tier['next'].name}, "
                        f"worth ${tier['uplift']:,.0f} more.",
                "cta": "See the ladder", "url": reverse("portal:incentive_detail")}

    return {"tone": "green", "label": "All clear",
            "text": "Nothing is waiting on you. Go sell.",
            "cta": "Log a sale", "url": reverse("portal:sales")}


def _home_agent(request, agent):
    active = Incentive.objects.exclude(bucket="previous")

    badges = agent.badges.all() if agent else Badge.objects.none()
    badges = list(badges)
    earned = [b for b in badges if b.is_earned]
    milestones = [b for b in badges if b.is_milestone]

    trend = list(agent.trend.all()) if agent else []
    peak = max([t.amount for t in trend], default=Decimal("1")) or Decimal("1")
    for point in trend:
        point.height_pct = round(point.amount / peak * 100)

    snapshot = agent.snapshots.filter(is_current=True).first() if agent else None
    # This agent's own earnings, not the sum of the programmes - those are
    # portal-wide and would read identically for everyone.
    monthly_earnings = snapshot.gross_commission if snapshot else Decimal("0.00")

    quests = list(agent.quests.all()) if agent else []

    return render(request, "portal/home.html", {
        "greeting": _greeting(),
        "quests": quests,
        "period_days_done": (snapshot.unit_target and 31 - snapshot.days_left) if snapshot else 0,
        "quests_done": len([q for q in quests if q.completed]),
        "quests_total": len(quests),
        "snapshot": snapshot,
        "monthly_earnings": monthly_earnings,
        "projected_payout": agent.scorecard.potential_payout if agent and hasattr(agent, "scorecard") else Decimal("0"),
        "active_incentives": active,
        "active_count": active.count(),
        "programs_total": Incentive.objects.count(),
        "badges": badges,
        "badges_earned": len(earned),
        "badges_total": len(badges),
        "milestones_earned": len([b for b in milestones if b.is_earned]),
        "milestones_total": len(milestones),
        "trend": trend,
        "chart": _area_chart(trend),
        "tier": _tier_progress(agent),
        "next_action": _next_action(agent, _tier_progress(agent)),
        "reward": request.session.pop("signin_reward", None),
        "active_nav": "home",
    })


# --------------------------------------------------------------------------
def _home_lead(request, agent):
    """Team Lead home: the squad, not the self."""
    from .views_team import _roster_rows

    teams = list(agent.visible_teams)
    team = teams[0] if teams else None
    rows = _roster_rows(team.agents if team else [])

    needs_help = [r for r in rows if r["attainment"] < 70]
    top = rows[0] if rows else None

    return render(request, "portal/home_lead.html", {
        "greeting": _greeting(),
        "insights": _insights([team] if team else [], rows, 0,
                              Dispute.objects.filter(
                                  agent__team=team,
                                  status__in=Dispute.OPEN_STATES).count() if team else 0),
        "team": team,
        "rows": rows[:5],
        "headcount": len(rows),
        "on_track": len([r for r in rows if r["attainment"] >= 100]),
        "needs_help": needs_help,
        "top": top,
        "team_points": sum(r["points"] for r in rows),
        "open_disputes": Dispute.objects.filter(
            agent__team=team, status__in=Dispute.OPEN_STATES
        ).count() if team else 0,
        "active_incentives": Incentive.objects.exclude(bucket="previous")[:3],
        "reward": request.session.pop("signin_reward", None),
        "active_nav": "home",
    })


def _insights(teams, people, plans_waiting, open_disputes):
    """
    Short observations derived from the data on screen.

    Deliberately computed, not generated: each line restates a fact the user
    can verify on the same page.
    """
    out = []
    if teams:
        best = max(teams, key=lambda t: t.attainment)
        worst = min(teams, key=lambda t: t.attainment)
        if best is not worst and best.attainment - worst.attainment >= 5:
            out.append(("good", f"{best.name} leads at {best.attainment}% attainment, "
                                f"{best.attainment - worst.attainment} points ahead of {worst.name}."))
    behind = [p for p in people if p["attainment"] < 70]
    if behind:
        out.append(("warn", f"{len(behind)} of {len(people)} agents are below 70% - "
                            f"{behind[0]['agent'].full_name} is furthest back at {behind[0]['attainment']}%."))
    on_track = [p for p in people if p["attainment"] >= 100]
    if on_track:
        out.append(("good", f"{len(on_track)} agents have already cleared quota this period."))
    if plans_waiting:
        out.append(("", f"{plans_waiting} incentive plan(s) are waiting on your approval."))
    if open_disputes:
        out.append(("warn", f"{open_disputes} disputes are open and unresolved."))
    return out


# --------------------------------------------------------------------------
def _home_manager(request, agent):
    """Manager home: every team, rolled up."""
    from .views_team import _roster_rows

    teams = list(agent.visible_teams.select_related("lead__user"))
    everyone = _roster_rows(agent.visible_agents)
    attainments = [t.attainment for t in teams]

    from .models import IncentivePlan
    waiting = IncentivePlan.objects.filter(
        team__in=teams, status=IncentivePlan.State.SUBMITTED).count()
    disputes_open = Dispute.objects.filter(
        agent__team__in=teams, status__in=Dispute.OPEN_STATES).count()

    return render(request, "portal/home_manager.html", {
        "greeting": _greeting(),
        "insights": _insights(teams, everyone, waiting, disputes_open),
        "plans_waiting": waiting,
        "teams": teams,
        "team_count": len(teams),
        "headcount": sum(t.headcount for t in teams),
        "avg_attainment": round(sum(attainments) / len(attainments)) if attainments else 0,
        "total_points": sum(r["points"] for r in everyone),
        "leaderboard": everyone[:5],
        "at_risk": [r for r in everyone if r["attainment"] < 70],
        "open_disputes": Dispute.objects.filter(
            agent__team__in=teams, status__in=Dispute.OPEN_STATES
        ).count(),
        "active_incentives": Incentive.objects.exclude(bucket="previous")[:3],
        "reward": request.session.pop("signin_reward", None),
        "active_nav": "home",
    })


@login_required
def claim_quest(request, quest_id):
    """
    Claim the XP for a finished quest. POST only - it changes state.

    Redirects back to Home with ?xp=<amount> so the page can play the
    reward animation once.
    """
    agent = _agent(request)
    if request.method != "POST" or agent is None:
        return redirect("portal:home")

    quest = get_object_or_404(Quest, pk=quest_id, agent=agent)
    before = agent.level
    awarded = quest.claim()

    if not awarded:
        return redirect("portal:home")

    agent.refresh_from_db()
    url = f"{reverse('portal:home')}?xp={awarded}&quest={quest.pk}"
    if agent.level > before:
        url += f"&levelup={agent.level}"
    return redirect(url)


# --------------------------------------------------------------------------
@login_required
def incentive_feed(request):
    """Active / Just Launched / Ending Soon / Previous."""
    month = request.GET.get("month", "All Months")
    previous = Incentive.objects.filter(bucket="previous")
    if month != "All Months":
        previous = previous.filter(period=month)

    # The buckets must not overlap. "Ending soon" used to be every live
    # programme with a week or less on it, which meant each one rendered
    # twice - once under Active and again under Ending Soon.
    ENDING_WITHIN = 7
    ending = Incentive.objects.exclude(bucket="previous").filter(
        days_left__lte=ENDING_WITHIN)
    ending_ids = list(ending.values_list("pk", flat=True))

    return render(request, "portal/incentive_feed.html", {
        "active": Incentive.objects.filter(bucket="active").exclude(pk__in=ending_ids),
        "launched": Incentive.objects.filter(bucket="launched").exclude(pk__in=ending_ids),
        "ending": ending,
        "previous": previous,
        "months": ["All Months"] + [p.label for p in Period.objects.all()],
        "month": month,
        "active_nav": "incentives",
    })


# --------------------------------------------------------------------------
@login_required
def incentive_detail(request, code=None):
    """Rank, tier ladder, points structure and MTD performance."""
    agent = _agent(request)
    scorecard = getattr(agent, "scorecard", None)
    incentive = (
        get_object_or_404(Incentive, short_code=code) if code
        else Incentive.objects.filter(bucket="active").first()
    )

    tiers = list(Tier.objects.all())
    points = scorecard.total_points if scorecard else 0
    current = scorecard.current_tier if scorecard else None

    # Annotate the ladder: which tier is current, and the gap to each next one.
    for i, tier in enumerate(tiers):
        tier.is_current = current is not None and tier.pk == current.pk
        nxt = tiers[i + 1] if i + 1 < len(tiers) else None
        tier.gap = max(0, nxt.threshold_points - points) if nxt else max(0, tier.threshold_points - points)
        tier.reached = points >= tier.threshold_points

    mtd = list(agent.mtd.all()) if agent else []
    focus = next((m for m in mtd if m.is_focus), None)

    # ---- Level-Up Mentor -------------------------------------------------
    # How far to the top tier, and the daily pace in each category that gets
    # there. Derived rather than stored, so it moves with the data.
    mentor = None
    top_tier = tiers[-1] if tiers else None
    if scorecard and top_tier:
        gap = max(0, top_tier.threshold_points - points)
        days = scorecard.days_remaining or 1
        per_day = gap / days
        mentor = {
            "tier": top_tier,
            "points_to_go": gap,
            "days": days,
            "per_day": round(per_day, 1),
            "recommendations": [
                {"label": r.short_label or r.label,
                 "units": round(per_day / r.points, 1) if r.points else 0}
                for r in PointsRule.objects.all()
            ],
        }

    return render(request, "portal/incentive_detail.html", {
        "mentor": mentor,
        "incentive": incentive,
        "scorecard": scorecard,
        "tiers": tiers,
        "points_rules": PointsRule.objects.all(),
        "mtd": mtd,
        "focus": focus,
        "active_nav": "incentives",
    })


# --------------------------------------------------------------------------
PRESET_TARGETS = [300, 500, 1000]


@login_required
def calculator(request):
    """
    'What is your earning target?' - work out units needed and a daily pace.

    All arithmetic happens here rather than in JavaScript so the numbers are
    testable and the page works without scripting.
    """
    agent = _agent(request)
    incentives = list(Incentive.objects.exclude(bucket="previous"))

    code = request.GET.get("incentive") or (incentives[0].short_code if incentives else None)
    incentive = next((i for i in incentives if i.short_code == code), None)
    target = request.GET.get("target")
    plan = None

    if incentive and target:
        try:
            target_value = Decimal(target)
        except (TypeError, ArithmeticError, ValueError):
            target_value = None

        if target_value and target_value > 0:
            days = incentive.days_left or 1
            if incentive.is_points_based:
                needed = max(0, int(target_value) - incentive.points_earned)
                unit_word = "pts"
            else:
                rate = incentive.rate_per_unit or Decimal("1")
                needed = max(0, int((target_value - incentive.earned) / rate + Decimal("0.999")))
                unit_word = "units"

            plan = {
                "target": target_value,
                # Units already sold, not money earned - the money goes in the
                # sub-line. These were the same field before, which read as
                # "already sold 60" when 60 was dollars.
                "already": (incentive.points_earned if incentive.is_points_based
                            else incentive.progress),
                "needed": needed,
                "daily": round(needed / days, 1),
                "days": days,
                "unit_word": unit_word,
                "achieved": needed == 0,
            }

            if request.method == "POST":
                SavedPlan.objects.create(
                    agent=agent, incentive=incentive, target_amount=target_value,
                    units_needed=needed, daily_target=plan["daily"],
                )
                return redirect(f"{request.path}?incentive={incentive.short_code}&target={target}&saved=1")

    return render(request, "portal/calculator.html", {
        "incentives": incentives,
        "incentive": incentive,
        "presets": PRESET_TARGETS,
        "target": target,
        "plan": plan,
        "saved": request.GET.get("saved"),
        "saved_plans": agent.plans.select_related("incentive")[:5] if agent else [],
        "active_nav": "calculator",
    })


# --------------------------------------------------------------------------
@login_required
def disputes(request):
    """
    Agents raise and track their own disputes. Leads and managers see the
    queue for everyone below them instead.
    """
    agent = _agent(request)
    if agent is None:
        return render(request, "portal/disputes.html", {"tickets": [], "visible": 0,
                                                        "active_nav": "disputes"})

    is_queue = agent.can_see_team
    if is_queue:
        tickets = list(
            Dispute.objects.filter(agent__in=agent.visible_agents)
            .select_related("agent__user", "agent__team")
        )
    else:
        tickets = list(agent.disputes.all())

    form = DisputeForm()

    if request.method == "POST":
        if request.POST.get("delete"):
            # Only ever your own ticket.
            agent.disputes.filter(ticket_no=request.POST["delete"]).delete()
            return redirect("portal:disputes")

        # A lead (or the manager above them) signs off an agent's dispute.
        decide = request.POST.get("decide")
        if decide and is_queue:
            ticket = get_object_or_404(Dispute, ticket_no=request.POST.get("ticket"))
            if not ticket.can_be_decided_by(agent):
                raise PermissionDenied("That dispute is not yours to decide.")
            ticket.status = (Dispute.State.IN_REVIEW if decide == "approve"
                             else Dispute.State.REJECTED)
            ticket.decided_by = agent
            ticket.decision_note = request.POST.get("note", "").strip()
            ticket.save(update_fields=["status", "decided_by", "decision_note"])
            return redirect(f"{reverse('portal:disputes')}?decided={ticket.ticket_no}")

        if not is_queue:
            form = DisputeForm(request.POST)
            if form.is_valid():
                ticket = form.save(commit=False)
                ticket.agent = agent
                ticket.ticket_no = Dispute.next_ticket_no()
                ticket.status = Dispute.State.AWAITING_LEAD
                ticket.raised_on = timezone.localdate()
                ticket.save()
                return redirect(f"{reverse('portal:disputes')}?raised={ticket.ticket_no}")

    category = request.GET.get("category", "All Categories")
    priority = request.GET.get("priority", "All Priorities")
    query = request.GET.get("q", "").strip().lower()

    visible = 0
    for ticket in tickets:
        ok = (
            (category == "All Categories" or ticket.category == category)
            and (priority == "All Priorities" or ticket.priority == priority)
            and (not query or query in ticket.search_blob)
        )
        ticket.is_hidden = not ok
        visible += ok

    return render(request, "portal/disputes.html", {
        "tickets": tickets,
        "form": form,
        "is_queue": is_queue,
        "visible": visible,
        "open_count": len([t for t in tickets if t.status in Dispute.OPEN_STATES]),
        "awaiting": [t for t in tickets if t.is_awaiting_decision],
        "decided": request.GET.get("decided"),
        "raised": request.GET.get("raised"),
        "categories": ["All Categories"] + [c.value for c in Dispute.Category],
        "priorities": ["All Priorities"] + [p.value for p in Dispute.Priority],
        "category": category,
        "priority": priority,
        "query": query,
        "active_nav": "disputes",
    })
