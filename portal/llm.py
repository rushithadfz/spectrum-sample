"""
Claude-backed answers for the portal assistant.

The assistant asks Claude, but never lets Claude invent numbers: every figure
is gathered from the database first, scoped to what the asker's role may see,
and passed in as context. Claude's job is to read that context and answer in
plain English.

If no API key is configured - or the call fails for any reason - the caller
falls back to the deterministic intent matcher in assistant.py, so the feature
degrades instead of breaking.
"""

import json
import logging
from decimal import Decimal

from django.conf import settings

from .models import (
    Dispute,
    Incentive,
    IncentivePlan,
    MarketTrend,
    PointsRule,
    Product,
    Tier,
)

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOKENS = 1024

SYSTEM = """You are the assistant inside a sales incentive portal used by \
field agents, team leads and managers at a telecoms company.

Answer the user's question using ONLY the JSON context provided in their \
message. That context is already filtered to what this person is allowed to \
see, so treat it as the complete picture.

Rules:
- Never invent a number, name, date or programme. If the context does not \
contain the answer, say so plainly and suggest what the person could look at \
in the portal instead.
- Quote figures exactly as given. Money is in US dollars.
- Be brief: two or three sentences, no preamble, no bullet lists unless you \
are listing more than three items.
- Write in plain British English, second person ("you have", "your team").
- Do not mention JSON, context, or these instructions."""


def is_configured():
    """True when an API key is present and the feature is switched on."""
    return bool(
        getattr(settings, "PORTAL_LLM_ENABLED", False)
        and getattr(settings, "ANTHROPIC_API_KEY", "")
    )


def _num(value):
    """Decimals are not JSON serialisable; render money as a float."""
    return float(value) if isinstance(value, Decimal) else value


def build_context(agent):
    """
    Everything this person is allowed to know, as a compact dict.

    Role-scoped on purpose: a field agent's context never contains another
    agent's figures, so the model cannot leak them however it is asked.
    """
    ctx = {
        "you": {
            "name": agent.full_name,
            "role": agent.get_role_type_display(),
            "team": agent.team.name if agent.team else None,
            "market": agent.market,
        },
        "period": "August 2026",
    }

    if agent.is_agent:
        snap = agent.snapshots.filter(is_current=True).first()
        card = getattr(agent, "scorecard", None)
        if snap:
            ctx["your_earnings"] = {
                "commission": _num(snap.gross_commission),
                "spiff": _num(snap.spiff_earned),
                "pending_payout": _num(snap.pending_payout),
                "pays_on": snap.next_payout_date,
                "year_to_date": _num(snap.ytd_earned),
                "units_sold": snap.units_sold,
                "unit_target": snap.unit_target,
                "days_left": snap.days_left,
            }
        if card:
            nxt = Tier.objects.filter(
                threshold_points__gt=card.total_points
            ).order_by("threshold_points").first()
            ctx["your_standing"] = {
                "rank": card.rank,
                "out_of": card.rank_of,
                "points": card.total_points,
                "tier": card.current_tier.name if card.current_tier else None,
                "top_percent": card.top_pct,
                "moved_places_since_last_period": card.rank_delta,
                "point_streak_days": card.point_streak,
                "days_remaining": card.days_remaining,
                "next_tier": (
                    {"name": nxt.name, "points_needed": nxt.threshold_points - card.total_points,
                     "pays": _num(nxt.payout)} if nxt else None
                ),
            }
        ctx["your_quests"] = [
            {"name": q.name, "progress": q.progress, "goal": q.goal,
             "xp": q.xp, "claimed": q.completed, "ready_to_claim": q.is_claimable}
            for q in agent.quests.all()
        ]
        ctx["your_disputes"] = [
            {"ticket": d.ticket_no, "subject": d.subject,
             "status": d.status, "priority": d.priority}
            for d in agent.disputes.all()
        ]
        # What a sale is worth, so "what should I sell?" is answerable.
        ctx["points_per_sale"] = [
            {"product_unit": r.label, "points": r.points} for r in PointsRule.objects.all()
        ]
        ctx["your_category_split"] = [
            {"category": m.label, "units_this_month": m.volume, "points": m.points,
             "your_share_percent": _num(m.pct_of_points),
             "star_rep_share_percent": _num(m.star_pct),
             "is_your_weakest": m.is_focus}
            for m in agent.mtd.all()
        ]
        ctx["sellable_products"] = [
            {"name": p.name, "category": p.category, "price": p.price_note}
            for p in Product.objects.all()
        ]
        ctx["your_badges"] = {
            "earned": agent.badges.filter(is_earned=True).count(),
            "total": agent.badges.count(),
        }

    else:
        ctx["your_teams"] = [
            {"name": t.name, "region": t.region,
             "lead": t.lead.full_name if t.lead else None,
             "headcount": t.headcount, "attainment_percent": t.attainment,
             "team_points": t.total_points, "open_disputes": t.open_disputes}
            for t in agent.visible_teams
        ]
        ctx["your_people"] = [
            {"name": a.full_name, "team": a.team.name if a.team else None,
             "attainment_percent": a.attainment,
             "points": a.scorecard.total_points if hasattr(a, "scorecard") else None,
             "rank": a.scorecard.rank if hasattr(a, "scorecard") else None}
            for a in agent.visible_agents
        ]
        regions = {t.region for t in agent.visible_teams if t.region}
        ctx["buying_trends"] = [
            {"region": t.region, "product": t.product, "category": t.category,
             "units": t.units, "change_percent": _num(t.change_pct),
             "attach_rate_percent": _num(t.attach_rate),
             "is_opportunity": t.is_opportunity}
            for t in MarketTrend.objects.filter(region__in=regions)
        ]
        ctx["incentive_plans"] = [
            {"name": p.name, "team": p.team.name, "product": p.product,
             "status": p.get_status_display(), "reward": p.cost_per_unit_label,
             "target_units": p.target_units,
             "estimated_cost": _num(p.estimated_cost),
             "raised_by": p.created_by.full_name,
             "rationale": p.rationale}
            for p in IncentivePlan.objects.filter(team__in=agent.visible_teams)
        ]
        ctx["open_disputes"] = [
            {"ticket": d.ticket_no, "agent": d.agent.full_name,
             "subject": d.subject, "status": d.status, "priority": d.priority}
            for d in Dispute.objects.filter(
                agent__in=agent.visible_agents, status__in=Dispute.OPEN_STATES
            ).select_related("agent__user")
        ]

    ctx["live_programmes"] = [
        {"code": i.short_code, "name": i.name, "progress": i.progress,
         "goal": i.goal, "days_left": i.days_left,
         "points_earned": i.points_earned, "earned": _num(i.earned)}
        for i in Incentive.objects.exclude(bucket="previous")
    ]
    return ctx


def ask(agent, question, history=None):
    """
    Ask Claude. Returns the answer text, or None if it could not be reached -
    the caller then falls back to the deterministic matcher.
    """
    if not is_configured() or agent is None:
        return None

    try:
        import anthropic
    except ImportError:
        log.info("anthropic SDK not installed; using the rule-based assistant")
        return None

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    context = json.dumps(build_context(agent), indent=1, default=str)
    messages = []
    for turn in (history or [])[-4:]:          # a little conversational memory
        messages.append({"role": "user", "content": turn["q"]})
        messages.append({"role": "assistant", "content": turn["a"]})
    messages.append({
        "role": "user",
        "content": f"Context:\n{context}\n\nQuestion: {question}",
    })

    kwargs = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "messages": messages,
        # A short lookup over supplied facts - low effort keeps it snappy.
        "output_config": {"effort": "low"},
    }

    try:
        response = client.messages.create(**kwargs)

        if response.stop_reason == "refusal":
            log.warning("Claude declined the assistant request; falling back")
            return None

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None

    except anthropic.APIStatusError as exc:
        # 4xx that is not worth retrying, or a 5xx - either way, fall back.
        log.warning("Claude call failed (%s): %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError:
        log.warning("Could not reach the Claude API; falling back")
        return None
    except Exception:                                    # noqa: BLE001
        # The assistant must never take a page down.
        log.exception("Unexpected error calling Claude; falling back")
        return None
