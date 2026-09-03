"""
Plan simulation.

A lead drafting an incentive wants one question answered before they submit
it: what does this cost, and does it buy anything? This module answers that
from live records - the team's current units, the region's budget, and what
a unit in that category actually earns - so the figures are the same ones
the rest of the portal reports.

Deliberately pure. Nothing here touches the request or writes to the
database, which is what makes the arithmetic testable on its own.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from .models import Budget, IncentivePlan, Offer, PerformanceSnapshot, Status

# A point is worth a cent when it is redeemed. Cash and points plans are not
# comparable until both are expressed in the same unit.
POINT_VALUE = Decimal("0.01")

# How much of a region's budget one plan may take before it is worth saying
# so out loud. Not a hard limit - a manager still decides.
BUDGET_WARN_SHARE = 25


def _money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Scenario:
    """One set of plan parameters to model. Not a database row."""

    name: str
    team: object
    category: str
    reward_type: str
    reward_amount: Decimal
    target_units: int

    @classmethod
    def from_plan(cls, plan, name=None):
        return cls(
            name=name or plan.name,
            team=plan.team,
            category=plan.category,
            reward_type=plan.reward_type,
            reward_amount=plan.reward_amount,
            target_units=plan.target_units,
        )


def baseline_units(team):
    """What the team already sells in a period, before any new incentive."""
    if team is None:
        return 0
    return sum(
        s.units_sold for s in PerformanceSnapshot.objects.filter(
            agent__team=team, is_current=True,
        )
    )


def unit_margin(category):
    """
    What one unit in this category earns the business, approximated by the
    commission already paid on it. If we do not know, we say so rather than
    inventing a number - callers check for None.
    """
    offers = Offer.objects.filter(category=category, status=Status.ACTIVE)
    rates = [o.commission for o in offers if o.commission]
    if not rates:
        return None
    return _money(sum(rates) / len(rates))


def region_budget(team):
    if team is None or not team.region:
        return None
    row = Budget.objects.filter(region=team.region).first()
    return row.amount if row else None


def run(scenario):
    """Model one scenario. Returns plain values ready for a template."""
    base = baseline_units(scenario.team)
    target = int(scenario.target_units or 0)
    incremental = target - base

    per_unit = Decimal(scenario.reward_amount or 0)
    if scenario.reward_type == IncentivePlan.Reward.POINTS:
        per_unit = per_unit * POINT_VALUE

    # You pay the reward on every qualifying unit, not only the extra ones.
    # Costing it any other way understates the plan.
    cost = _money(per_unit * target)

    margin = unit_margin(scenario.category)
    budget = region_budget(scenario.team)

    notes = []
    if incremental <= 0:
        notes.append(
            "The target is at or below what the team already sells, so this "
            "buys no extra units - it pays for volume you have."
        )
    if margin is not None and per_unit > margin:
        notes.append(
            f"The reward is more per unit ({_money(per_unit)}) than a unit in "
            f"this category earns ({margin}). Every sale loses money."
        )
    share = None
    if budget:
        share = int((cost / budget * 100).to_integral_value(rounding=ROUND_HALF_UP))
        if share >= BUDGET_WARN_SHARE:
            notes.append(
                f"This one plan takes {share}% of the {scenario.team.region} budget."
            )

    return {
        "scenario": scenario,
        "baseline": base,
        "target": target,
        "incremental": incremental,
        "reward_per_unit": _money(per_unit),
        "cost": cost,
        "cost_per_incremental": _money(cost / incremental) if incremental > 0 else None,
        "unit_margin": margin,
        "budget": budget,
        "budget_share": share,
        "notes": notes,
        # green when it buys units and nothing was flagged
        "verdict": "red" if any("loses money" in n for n in notes)
                   else ("amber" if notes else "green"),
    }


def compare(a, b):
    """
    Two modelled scenarios and the difference between them, always stated
    as B relative to A so the direction is never ambiguous.
    """
    ra, rb = run(a), run(b)
    return {
        "a": ra,
        "b": rb,
        "cost_delta": rb["cost"] - ra["cost"],
        "units_delta": rb["incremental"] - ra["incremental"],
        "cheaper": "b" if rb["cost"] < ra["cost"] else ("a" if ra["cost"] < rb["cost"] else None),
    }
