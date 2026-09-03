"""Context shared by every template: the agent, and the app-bar chrome."""

import json


def agent(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"agent": None}
    return {"agent": getattr(user, "agent", None)}


def chrome(request):
    """
    Period selector, notification tray and command-palette index.

    Only built for signed-in users so the sign-in page stays a plain query.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    # Imported here to keep the module importable before migrations run.
    from django.urls import reverse

    from .models import Incentive, Notification, Period

    periods = list(Period.objects.all())
    notifications = list(Notification.objects.all())

    palette = [
        {"label": "Home", "hint": "page", "url": reverse("portal:home")},
        {"label": "Incentives", "hint": "page", "url": reverse("portal:incentive_feed")},
        {"label": "Points Incentive", "hint": "page", "url": reverse("portal:incentive_detail")},
        {"label": "Earnings Calculator", "hint": "page", "url": reverse("portal:calculator")},
        {"label": "Disputes", "hint": "page", "url": reverse("portal:disputes")},
        {"label": "Product catalog", "hint": "page", "url": reverse("portal:products")},
    ]
    for incentive in Incentive.objects.all():
        palette.append({
            "label": incentive.name,
            "hint": incentive.short_code or "incentive",
            "url": reverse("portal:incentive_detail_code", args=[incentive.short_code])
            if incentive.short_code else reverse("portal:incentive_detail"),
        })

    from . import assistant

    return {
        "ask_history": request.session.get("ask_history", []),
        "ask_suggestions": assistant.SUGGESTIONS.get(
            getattr(getattr(user, "agent", None), "role_type", None), [])[:3],
        "periods": periods,
        "current_period": next((p for p in periods if p.is_current), None),
        "notifications": notifications,
        "palette_json": json.dumps(palette),
    }


def assistant_mood(request):
    """
    The character's mood, on every page.

    It is derived from the same records the rest of the portal reads, so the
    figure is never cheerful while a payout sits rejected. Cheapest checks
    first, and it never raises - a decorative element must not be able to
    break a page.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"assistant_mood": "blue"}

    try:
        # Inside the try: accessing the profile can itself fail, and a
        # decorative element must never take a page down with it.
        person = getattr(user, "agent", None)
        if person is None:
            return {"assistant_mood": "blue"}

        from .models import Dispute, IncentivePlan, PayoutException, Sale

        if person.is_agent:
            sales = list(person.sales.all())
            if any(s.approval == Sale.Approval.REJECTED for s in sales):
                return {"assistant_mood": "red"}
            if any(s.is_awaiting_decision for s in sales):
                return {"assistant_mood": "amber"}
            if any(d.is_awaiting_decision for d in person.disputes.all()):
                return {"assistant_mood": "amber"}
            return {"assistant_mood": "green"}

        # A lead or manager is judged on what is queued for them to decide.
        people = list(person.visible_agents)
        teams = list(person.visible_teams)

        if person.is_manager and PayoutException.objects.filter(
                agent__team__in=teams,
                status=PayoutException.State.PENDING).exists():
            return {"assistant_mood": "red"}

        waiting = (
            Sale.objects.filter(agent__in=people,
                                approval=Sale.Approval.AWAITING_LEAD).exists()
            or Dispute.objects.filter(agent__in=people,
                                      status__in=Dispute.OPEN_STATES).exists()
            or IncentivePlan.objects.filter(
                team__in=teams, status=IncentivePlan.State.SUBMITTED).exists()
        )
        return {"assistant_mood": "amber" if waiting else "green"}
    except Exception:
        return {"assistant_mood": "blue"}
