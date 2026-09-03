"""
The in-portal assistant.

Two engines, one entry point (`respond`):

1. Claude, when an API key is configured. It is given database context that
   has already been scoped to the asker's role and told to answer only from
   it - see llm.py.
2. A deterministic intent matcher, used when Claude is unavailable or the
   call fails. It matches keywords and answers straight from the database.

Either way the figures come from this portal, never from a model's memory.

Adding an intent means adding one entry to INTENTS: keywords, the roles that
may ask it, and a function that returns (answer, list_of_links).
"""

from decimal import Decimal

from .models import Dispute, IncentivePlan, Incentive, MarketTrend, RoleType


def _money(n):
    return f"${Decimal(n):,.2f}"


# --------------------------------------------------------------------------
# Answer builders. Each takes (agent) and returns (text, links)
# --------------------------------------------------------------------------
def _earnings(agent):
    snap = agent.snapshots.filter(is_current=True).first()
    if not snap:
        return "I cannot find a current period for you yet.", []
    return (
        f"You have earned {_money(snap.gross_commission)} in commission this period, "
        f"plus {_money(snap.spiff_earned)} in SPIFF. "
        f"{_money(snap.pending_payout)} is pending, paying {snap.next_payout_date}. "
        f"Year to date you are on {_money(snap.ytd_earned)}."
    ), [("See your scorecard", "portal:incentive_detail")]


def _rank(agent):
    card = getattr(agent, "scorecard", None)
    if not card:
        return "You do not have a scorecard for this period.", []
    move = ""
    if card.rank_delta:
        direction = "up" if card.rank_delta > 0 else "down"
        move = f" You have moved {direction} {abs(card.rank_delta)} places since last period."
    return (
        f"You are ranked {card.rank} of {card.rank_of} on {card.total_points} points, "
        f"which puts you in the top {card.top_pct}%.{move}"
    ), [("Open your scorecard", "portal:incentive_detail")]


def _next_tier(agent):
    card = getattr(agent, "scorecard", None)
    if not card:
        return "You do not have a scorecard for this period.", []
    from .models import Tier

    nxt = Tier.objects.filter(threshold_points__gt=card.total_points).order_by(
        "threshold_points").first()
    if not nxt:
        return (
            f"You are already at the top tier on {card.total_points} points.", [])
    gap = nxt.threshold_points - card.total_points
    per_day = round(gap / card.days_remaining, 1) if card.days_remaining else gap
    return (
        f"{gap} points to {nxt.name}, which pays {_money(nxt.payout)}. "
        f"With {card.days_remaining} days left that is about {per_day} points a day."
    ), [("Open the earnings calculator", "portal:calculator")]


def _what_to_sell(agent):
    """
    "What should I sell to get there?" - answered from the points structure,
    the gap to the next tier, and where this agent trails a Star rep.
    """
    from .models import PointsRule, Tier

    card = getattr(agent, "scorecard", None)
    rules = list(PointsRule.objects.all())
    if not card or not rules:
        return "I do not have a points structure for your plan yet.", []

    best = max(rules, key=lambda r: r.points)
    ladder = ", ".join(f"{r.label} {r.points} pts" for r in rules)

    top = Tier.objects.order_by("-threshold_points").first()
    gap = max(0, top.threshold_points - card.total_points) if top else 0
    days = card.days_remaining or 1

    text = f"Points per sale: {ladder}. {best.label} is worth the most, so lead with it."

    if gap:
        per_day = gap / days
        units = round(per_day / best.points, 1)
        text += (
            f" You need {gap} more points for {top.name} in {days} days"
            f" - about {units} {best.label} a day, or the equivalent in the others."
        )

    # Where they trail a Star rep is the sharpest steer available.
    focus = next((m for m in agent.mtd.all() if m.is_focus), None)
    if focus is not None:
        text += (
            f" Your biggest gap is {focus.label}: you are on {focus.pct_of_points}%"
            f" of points against a Star rep's {focus.star_pct}%."
        )

    return text, [
        ("See the points structure", "portal:incentive_detail"),
        ("Open the product catalog", "portal:products"),
    ]


def _quests(agent):
    quests = list(agent.quests.all())
    done = [q for q in quests if q.completed]
    claimable = [q for q in quests if q.is_claimable]
    text = f"You have finished {len(done)} of {len(quests)} quests today."
    if claimable:
        text += (" " + ", ".join(q.name for q in claimable)
                 + (" is" if len(claimable) == 1 else " are") + " ready to claim.")
    return text, [("Go to your quests", "portal:home")]


def _my_disputes(agent):
    tickets = list(agent.disputes.all())
    if not tickets:
        return "You have no open disputes.", [("Raise one", "portal:disputes")]
    open_ones = [t for t in tickets if t.status in Dispute.OPEN_STATES]
    return (
        f"You have {len(tickets)} disputes, {len(open_ones)} still open. "
        + "; ".join(f"{t.ticket_no} {t.subject} ({t.status})" for t in tickets[:3])
    ), [("Open disputes", "portal:disputes")]


def _incentives(agent):
    live = list(Incentive.objects.exclude(bucket="previous"))
    if not live:
        return "There are no live programmes right now.", []
    bits = [f"{i.name} ({i.progress}/{i.goal}, {i.days_left}d left)" for i in live]
    return "Live programmes: " + "; ".join(bits) + ".", [
        ("See all incentives", "portal:incentive_feed")]


# ---- lead / manager ----
def _team_standing(agent):
    teams = list(agent.visible_teams)
    if not teams:
        return "You do not have any teams assigned.", []
    parts = []
    for t in teams:
        parts.append(f"{t.name}: {t.attainment}% attainment across {t.headcount} agents")
    return "; ".join(parts) + ".", [("Open the roster", "portal:team")]


def _who_needs_help(agent):
    behind = [a for a in agent.visible_agents if a.attainment < 70]
    if not behind:
        return "Everyone below you is at or above 70% attainment.", []
    listed = ", ".join(f"{a.full_name} ({a.attainment}%)" for a in behind[:5])
    return f"{len(behind)} people are below 70%: {listed}.", [
        ("Open the roster", "portal:team")]


def _top_performer(agent):
    people = sorted(agent.visible_agents, key=lambda a: a.attainment, reverse=True)
    if not people:
        return "There is nobody below you yet.", []
    best = people[0]
    return (
        f"{best.full_name} leads on {best.attainment}% attainment"
        f"{' in ' + best.team.name if best.team else ''}."
    ), [("Open the roster", "portal:team")]


def _team_disputes(agent):
    tickets = Dispute.objects.filter(
        agent__in=agent.visible_agents, status__in=Dispute.OPEN_STATES)
    if not tickets:
        return "No open disputes across your teams.", []
    return f"{tickets.count()} disputes are open across your teams.", [
        ("Open the queue", "portal:disputes")]


def _trends(agent):
    regions = sorted({t.region for t in agent.visible_teams if t.region})
    rows = list(MarketTrend.objects.filter(region__in=regions))
    if not rows:
        return "No trend data for your region yet.", []
    rising = sorted([r for r in rows if r.change_pct > 0],
                    key=lambda r: r.change_pct, reverse=True)[:3]
    gaps = [r for r in rows if r.is_opportunity]
    text = "Rising in your region: " + ", ".join(
        f"{r.product} ({r.change_pct:+}%)" for r in rising) + "."
    if gaps:
        text += (" Biggest opportunity: " + gaps[0].product
                 + f" - selling well but only {gaps[0].attach_rate}% attach.")
    return text, [("Open buying trends", "portal:trends")]


def _plans(agent):
    if agent.is_manager:
        queue = IncentivePlan.objects.filter(
            team__in=agent.visible_teams, status=IncentivePlan.State.SUBMITTED)
        if not queue:
            return "Nothing is waiting for your approval.", [("Open plans", "portal:plans")]
        listed = "; ".join(f"{p.name} for {p.team.name} ({_money(p.estimated_cost)})"
                           for p in queue[:3])
        return f"{queue.count()} plans await your approval: {listed}.", [
            ("Review them", "portal:plans")]

    mine = IncentivePlan.objects.filter(created_by=agent)
    if not mine:
        return "You have not drafted any plans yet.", [("Build one", "portal:plan_new")]
    counts = {}
    for p in mine:
        counts[p.get_status_display()] = counts.get(p.get_status_display(), 0) + 1
    return ("Your plans: " + ", ".join(f"{v} {k.lower()}" for k, v in counts.items())
            + "."), [("Open plans", "portal:plans")]


# --------------------------------------------------------------------------
# Intent table
# --------------------------------------------------------------------------
AGENT = RoleType.AGENT
LEAD = RoleType.LEAD
MANAGER = RoleType.MANAGER
ALL = (AGENT, LEAD, MANAGER)


def _my_sales(agent):
    from .models import Sale
    sales = list(agent.sales.all())
    if not sales:
        return ("You have not logged a sale yet. Log one and your team lead "
                "signs off the incentive."), [("Log a sale", "portal:sales")]
    waiting = [s for s in sales if s.is_awaiting_decision]
    approved = sum((s.earned for s in sales), Decimal("0.00"))
    held = sum((s.incentive_value for s in waiting), Decimal("0.00"))
    text = f"{len(sales)} sale(s) logged. {_money(approved)} is approved and payable"
    if waiting:
        lead = agent.team.lead.first_name if agent.team and agent.team.lead else "your lead"
        text += f", and {_money(held)} across {len(waiting)} sale(s) is still with {lead}."
    else:
        text += ", and nothing is waiting on approval."
    return text, [("See your sales", "portal:sales")]


def _how_to_log(agent):
    return ("Open Log a Sale, choose the offer, the customer and how many "
            "units. The incentive is worked out from the offer, so you never "
            "type a figure. It then goes to your team lead to approve."
            ), [("Log a sale", "portal:sales")]


def _streak(agent):
    return (f"You are on a {agent.streak_days}-day sign-in streak, at level "
            f"{agent.level} with {agent.xp_into_level} of "
            f"{agent.xp_for_next_level} XP towards the next one. Signing in "
            f"each day also gives you a roll of the die - the face you roll "
            f"is worth ten XP a pip."), []


def _badges(agent):
    earned = [b for b in agent.badges.all() if b.is_earned]
    total = agent.badges.count()
    return (f"You have earned {len(earned)} of {total} badges. The points "
            f"page lists every one and what unlocks it."
            ), [("Points Incentive", "portal:incentive_detail")]


def _approvals_waiting(agent):
    from .models import Sale
    people = list(agent.visible_agents)
    waiting = list(Sale.objects.filter(agent__in=people,
                                       approval=Sale.Approval.AWAITING_LEAD))
    if not waiting:
        return "Nothing is waiting on your sign-off.", []
    held = sum((s.incentive_value for s in waiting), Decimal("0.00"))
    return (f"{len(waiting)} sale(s) are waiting on you, holding "
            f"{_money(held)}."), [("Sales approvals", "portal:sales")]


def _close_status(agent):
    from .models import PeriodClose
    regions = {t.region for t in agent.visible_teams}
    row = PeriodClose.objects.filter(region__in=regions).first()
    if row is None or row.status == PeriodClose.State.OPEN:
        return ("The period is still open. Clear every payout exception, then "
                "calculate, then approve for payroll."), [("Month-end close", "portal:close")]
    if row.status == PeriodClose.State.CALCULATED:
        return (f"{_money(row.total)} has been calculated and is waiting for "
                f"your approval."), [("Month-end close", "portal:close")]
    return (f"{_money(row.total)} was approved for payroll by "
            f"{row.approved_by.full_name if row.approved_by else 'a manager'}. "
            f"The period is locked."), [("Month-end close", "portal:close")]


def _reports(agent):
    return ("There are five reports - payout register, sales ledger, dispute "
            "log, team summary and close statement. Each previews in the "
            "browser and downloads as CSV, scoped to what you can see."
            ), [("Reports", "portal:reports")]


def _find_agent(agent):
    return (f"The agent directory lists all {len(list(agent.visible_agents))} "
            f"people you can see. You can search by name, team or market, "
            f"filter by team and sort by any column."
            ), [("Agent directory", "portal:directory")]


def _channels_answer(agent):
    from .models import Channel
    regions = {t.region for t in agent.visible_teams}
    rows = list(Channel.objects.filter(region__in=regions))
    if not rows:
        return "There is no channel data for your region.", []
    best = max(rows, key=lambda c: c.attainment)
    worst = min(rows, key=lambda c: c.attainment)
    return (f"{len(rows)} channels. {best.name} is strongest at "
            f"{best.attainment}%, {worst.name} is weakest at "
            f"{worst.attainment}%."), [("Channels", "portal:channels")]


def _settings_answer(agent):
    from .models import Setting
    regions = {t.region for t in agent.visible_teams}
    row = Setting.objects.filter(region__in=regions).first()
    threshold = row.coaching_threshold if row else 70
    return (f"Coaching is currently flagged below {threshold}% attainment. "
            f"Thresholds are set per region on the settings page."
            ), [("Settings", "portal:settings")]


INTENTS = [
    (("earn", "earning", "commission", "paid", "payout", "money", "spiff"), (AGENT,), _earnings),
    (("rank", "ranking", "position", "standing", "leaderboard"), (AGENT,), _rank),
    (("tier", "star", "next level", "how many points", "points to"), (AGENT,), _next_tier),
    (("what should i sell", "which product", "what do i sell", "products to sell",
      "what to sell", "how do i get there", "reach it", "best product",
      "product", "sell"), (AGENT,), _what_to_sell),
    (("quest", "task", "daily", "xp"), (AGENT,), _quests),
    (("my dispute", "my ticket", "raise a dispute", "dispute"), (AGENT,), _my_disputes),
    (("incentive", "programme", "program", "live"), ALL, _incentives),

    (("team", "squad", "attainment", "roster"), (LEAD, MANAGER), _team_standing),
    (("help", "behind", "struggling", "coaching", "at risk", "below"), (LEAD, MANAGER), _who_needs_help),
    (("top", "best", "leading", "highest"), (LEAD, MANAGER), _top_performer),
    (("dispute", "ticket", "queue"), (LEAD, MANAGER), _team_disputes),
    (("trend", "buying", "customer", "selling", "market", "area", "region"), (LEAD, MANAGER), _trends),
    (("plan", "approval", "approve", "pending"), (LEAD, MANAGER), _plans),

    # Added with the sales, close, reports, directory and settings pages.
    (("my sale", "my sales", "sales i", "logged", "sold"), (AGENT,), _my_sales),
    (("log a sale", "how do i log", "record a sale", "add a sale",
      "how to log"), (AGENT,), _how_to_log),
    (("streak", "level", "how much xp", "my xp", "dice", "die", "roll"), (AGENT,), _streak),
    (("badge", "achievement", "medal", "unlocked"), (AGENT,), _badges),

    (("waiting on me", "sign off", "sign-off", "to approve", "approvals",
      "awaiting my"), (LEAD, MANAGER), _approvals_waiting),
    (("close", "month end", "month-end", "payroll", "lock the period",
      "calculate"), (MANAGER,), _close_status),
    (("report", "export", "csv", "download"), (LEAD, MANAGER), _reports),
    (("find", "directory", "look up", "search for", "who is"), (LEAD, MANAGER), _find_agent),
    (("channel", "retail", "inbound", "outbound", "d2d"), (LEAD, MANAGER), _channels_answer),
    (("setting", "threshold", "coaching level", "configure"), (MANAGER,), _settings_answer),
]

SUGGESTIONS = {
    AGENT: [
        "How much have I earned this period?",
        "What is my rank?",
        "How many points to the next tier?",
        "What products should I sell to reach the next tier?",
        "What quests are left today?",
        "Do I have any open disputes?",
    ],
    LEAD: [
        "How is my team doing?",
        "Who is below quota?",
        "What are the buying trends in my area?",
        "What is happening with my plans?",
        "Any open disputes on my team?",
    ],
    MANAGER: [
        "What are the buying trends in my region?",
        "What plans are waiting for my approval?",
        "How are my teams performing?",
        "Who needs coaching?",
        "Who is my top performer?",
    ],
}


def respond(agent, question, history=None):
    """
    Answer a question, preferring Claude when it is configured.

    Returns (text, links, engine). `engine` is "claude" or "rules" so the UI
    can be honest about which one replied.
    """
    from . import llm

    text = llm.ask(agent, question, history=history)
    if text:
        # Reuse the matcher purely to attach a relevant deep link.
        _, links = answer(agent, question)
        return text, links, "claude"

    text, links = answer(agent, question)
    return text, links, "rules"


# --------------------------------------------------------------------------
# Small talk
#
# "hi" is two characters, so it loses every longest-keyword contest against
# the real intents. Social openers are therefore matched first, on whole
# words, before scoring begins - otherwise a greeting fell through to
# "I did not recognise that one", which is a rude way to start.
# --------------------------------------------------------------------------
NAME = "Spidey"

GREETINGS = {"hi", "hey", "hello", "yo", "hiya", "howdy", "sup",
             "good morning", "good afternoon", "good evening", "morning"}
THANKS = {"thanks", "thank you", "ta", "cheers", "thx", "appreciate it"}
FAREWELL = {"bye", "goodbye", "see you", "later", "cya", "good night"}
IDENTITY = {"who are you", "what are you", "your name", "who r u",
            "what can you do", "what do you do", "help", "what can i ask"}
HOWAREYOU = {"how are you", "how's it going", "hows it going", "you ok",
             "how are u", "you good"}


def _words(q):
    import re
    return set(re.findall(r"[a-z']+", q))


def _social(agent, q):
    """Return (text, links) for small talk, or None to carry on matching."""
    words = _words(q)
    first = agent.first_name if agent else "there"

    if q in GREETINGS or (words & {"hi", "hey", "hello", "yo", "hiya"}) or             any(g in q for g in ("good morning", "good afternoon", "good evening")):
        return (
            f"Hi {first} - {NAME} here. Ask me about your earnings, your rank, "
            f"what to sell next, or anything else on your dashboard."
        ), []

    if any(t in q for t in THANKS):
        return f"Any time, {first}.", []

    if any(f in q for f in FAREWELL):
        return f"See you, {first}. Go close something.", []

    if any(h in q for h in HOWAREYOU):
        return (
            f"Running fine, thanks. More to the point, {first}: ask me where "
            f"your numbers stand and I will pull them."
        ), []

    if any(i in q for i in IDENTITY):
        return (
            f"I am {NAME}, the assistant built into this portal. I answer from "
            f"your own records - earnings, rank, tier, live programmes, "
            f"disputes and what to sell next. I never make figures up."
        ), []

    return None


def answer(agent, question):
    """
    Match the question to an intent this person is allowed to ask, and answer
    it from the database. Returns (text, links).
    """
    if agent is None:
        return "I need an agent profile to answer that.", []

    q = (question or "").strip().lower()
    if not q:
        return f"{NAME} here. Ask me something about your numbers.", []

    social = _social(agent, q)
    if social is not None:
        return social

    best, best_score = None, 0
    for keywords, roles, fn in INTENTS:
        if agent.role_type not in roles:
            continue
        # Longest matching keyword wins, so "my dispute" beats "dispute".
        score = max((len(k) for k in keywords if k in q), default=0)
        if score > best_score:
            best, best_score = fn, score

    if best is None:
        # Name what this person can actually ask, rather than shrugging.
        askable = sorted({k[0] for keywords, roles, _ in INTENTS
                          if agent.role_type in roles for k in [keywords]})
        return (
            f"I did not catch that one, {agent.first_name}. I answer from the "
            f"portal's own records, so try things like "
            f"“how much have I earned”, “what is my rank” "
            f"or “what should I sell”."
        ), []

    return best(agent)
