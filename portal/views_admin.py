"""
Channels and Settings.

Channels is read-only: figures come from the wider business, not from this
portal's own records, so there is nothing here to edit.

Settings is the opposite - the thresholds it holds are read by other pages,
so a change here has to actually move what those pages show. They are stored
per region rather than globally, because a threshold that made sense in the
Southwest is not automatically right in the Northeast.
"""

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.shortcuts import redirect, render

from .models import Channel, RoleType, Setting
from .views_team import role_required


@role_required(RoleType.LEAD, RoleType.MANAGER)
def channels(request):
    viewer = request.user.agent
    teams = list(viewer.visible_teams)
    regions = sorted({t.region for t in teams})

    rows = list(Channel.objects.filter(region__in=regions).order_by("order", "name"))
    total_spend = sum((c.spend for c in rows), Decimal("0.00"))
    total_agents = sum(c.agents for c in rows)

    for c in rows:
        # Share of regional spend, so a big channel is visibly big.
        c.share = round(float(c.spend) / float(total_spend) * 100) if total_spend else 0

    best = max(rows, key=lambda c: c.attainment, default=None)
    worst = min(rows, key=lambda c: c.attainment, default=None)

    return render(request, "portal/channels.html", {
        "rows": rows,
        "regions": regions,
        "total_spend": total_spend,
        "total_agents": total_agents,
        "avg_payout": (total_spend / total_agents) if total_agents else Decimal("0"),
        "best": best,
        "worst": worst,
        "active_nav": "channels",
    })


class SettingsForm(forms.ModelForm):
    class Meta:
        model = Setting
        fields = ["coaching_threshold", "exception_threshold",
                  "close_reminder_days", "notify_on_dispute",
                  "notify_on_plan", "notify_on_close"]
        labels = {
            "coaching_threshold": "Flag an agent for coaching below (%)",
            "exception_threshold": "Hold a payout for review above ($)",
            "close_reminder_days": "Remind me to close the period (days before)",
            "notify_on_dispute": "A dispute needs my decision",
            "notify_on_plan": "A plan is waiting for approval",
            "notify_on_close": "The period is ready to close",
        }

    def clean_coaching_threshold(self):
        v = self.cleaned_data["coaching_threshold"]
        if not 0 < v < 100:
            raise forms.ValidationError("A coaching threshold must sit between 1 and 99.")
        return v

    def clean_exception_threshold(self):
        v = self.cleaned_data["exception_threshold"]
        if v <= 0:
            raise forms.ValidationError("A hold threshold has to be more than zero.")
        return v


@role_required(RoleType.MANAGER)
def settings(request):
    manager = request.user.agent
    teams = list(manager.visible_teams)
    region = (teams[0].region if teams else "") or manager.market

    record, _ = Setting.objects.get_or_create(region=region)

    if request.method == "POST":
        form = SettingsForm(request.POST, instance=record)
        if form.is_valid():
            record = form.save(commit=False)
            record.updated_by = manager
            record.save()
            messages.success(request, "Settings saved. They apply to this region now.")
            return redirect("portal:settings")
    else:
        form = SettingsForm(instance=record)

    # Show what the thresholds currently catch, so a number is not abstract.
    people = list(manager.visible_agents)
    below = [a for a in people if a.attainment < record.coaching_threshold]

    return render(request, "portal/settings.html", {
        "form": form,
        "record": record,
        "region": region,
        "headcount": len(people),
        "below": below,
        "active_nav": "settings",
    })
