"""
Market trends, the incentive plan builder, and the approval workflow.

Team leads read the trends for their region and draft a plan; managers who
own that team approve or reject it. Every permission check is server-side.
"""


from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import assistant, llm
from .models import Category, IncentivePlan, MarketTrend, RoleType, Team
from .views_team import role_required


# --------------------------------------------------------------------------
# Trends
# --------------------------------------------------------------------------
@role_required(RoleType.LEAD, RoleType.MANAGER)
def trends(request):
    """What customers in this person's region are buying."""
    agent = request.user.agent
    regions = sorted({t.region for t in agent.visible_teams if t.region})

    chosen = request.GET.get("region") or (regions[0] if regions else "")
    if chosen not in regions:
        chosen = regions[0] if regions else ""

    rows = list(MarketTrend.objects.filter(region=chosen))
    peak = max([r.units for r in rows], default=1) or 1
    for r in rows:
        r.bar_pct = round(r.units / peak * 100)

    rising = sorted([r for r in rows if r.change_pct > 0],
                    key=lambda r: r.change_pct, reverse=True)
    falling = sorted([r for r in rows if r.change_pct < 0], key=lambda r: r.change_pct)

    # Category mix, for the share breakdown.
    mix = {}
    for r in rows:
        mix[r.category] = mix.get(r.category, 0) + r.units
    total_units = sum(mix.values()) or 1
    mix_rows = sorted(
        ({"category": c, "units": u, "pct": round(u / total_units * 100)}
         for c, u in mix.items()),
        key=lambda m: m["units"], reverse=True,
    )

    return render(request, "portal/trends.html", {
        "regions": regions,
        "region": chosen,
        "rows": rows,
        "rising": rising[:3],
        "falling": falling[:3],
        "opportunities": [r for r in rows if r.is_opportunity],
        "mix": mix_rows,
        "total_units": total_units,
        "active_nav": "trends",
    })


# --------------------------------------------------------------------------
# Plan builder
# --------------------------------------------------------------------------
class PlanForm(forms.ModelForm):
    class Meta:
        model = IncentivePlan
        fields = ["name", "team", "product", "category", "reward_type",
                  "reward_amount", "target_units", "runs_from", "runs_to", "rationale"]
        widgets = {
            "runs_from": forms.DateInput(attrs={"type": "date"}),
            "runs_to": forms.DateInput(attrs={"type": "date"}),
            "rationale": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Which trend does this respond to, and why this reward?",
            }),
            "name": forms.TextInput(attrs={"placeholder": "e.g. 5G Gateway Push - September"}),
            "product": forms.TextInput(attrs={"placeholder": "e.g. 5G Home Gateway"}),
        }

    def __init__(self, *args, agent=None, **kwargs):
        super().__init__(*args, **kwargs)
        # You can only write a plan for a team you are responsible for.
        teams = agent.visible_teams if agent else Team.objects.none()
        self.fields["team"].queryset = teams
        self.fields["rationale"].required = True

        # With one team there is nothing to choose - do not make them pick.
        if teams.count() == 1:
            self.fields["team"].empty_label = None
            self.fields["team"].initial = teams.first()

        # The model defaults to 0, which the validator then rejects. Show an
        # empty box with a hint instead of a value the user has to clear.
        for name, hint in (("reward_amount", "e.g. 15.00"), ("target_units", "e.g. 120")):
            field = self.fields[name]
            field.widget.attrs.setdefault("placeholder", hint)
            if not self.instance.pk:
                field.initial = None

    def clean(self):
        data = super().clean()
        starts, ends = data.get("runs_from"), data.get("runs_to")
        if starts and ends and ends < starts:
            self.add_error("runs_to", "The end date cannot be before the start date.")
        if (data.get("reward_amount") or 0) <= 0:
            self.add_error("reward_amount", "Set a reward greater than zero.")
        if (data.get("target_units") or 0) <= 0:
            self.add_error("target_units", "Set a target above zero.")
        return data


@role_required(RoleType.LEAD, RoleType.MANAGER)
def plan_list(request):
    """Leads see what they drafted; managers see the queue for their teams."""
    agent = request.user.agent
    if agent.is_manager:
        plans = IncentivePlan.objects.filter(team__in=agent.visible_teams)
    else:
        plans = IncentivePlan.objects.filter(created_by=agent)

    plans = plans.select_related("team", "created_by__user", "decided_by__user")
    awaiting = [p for p in plans if p.status == IncentivePlan.State.SUBMITTED]

    return render(request, "portal/plans.html", {
        "plans": plans,
        "awaiting": awaiting,
        "approved": [p for p in plans if p.status == IncentivePlan.State.APPROVED],
        "can_create": True,
        "active_nav": "plans",
    })


@role_required(RoleType.LEAD, RoleType.MANAGER)
def plan_new(request, plan_id=None):
    """Draft or edit a plan. Prefills from a trend when one is passed in."""
    agent = request.user.agent
    plan = None
    if plan_id:
        plan = get_object_or_404(IncentivePlan, pk=plan_id)
        if plan.created_by_id != agent.pk:
            raise PermissionDenied("That plan is not yours to edit.")
        if not plan.is_editable:
            raise PermissionDenied("A submitted plan cannot be edited.")

    if request.method == "POST":
        form = PlanForm(request.POST, instance=plan, agent=agent)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.created_by = agent
            if saved.status == IncentivePlan.State.REJECTED:
                saved.status = IncentivePlan.State.DRAFT   # editing clears the rejection
            saved.save()
            if request.POST.get("submit_now"):
                saved.status = IncentivePlan.State.SUBMITTED
                saved.save(update_fields=["status"])
                messages.success(request, f"{saved.name} sent for approval.")
            else:
                messages.success(request, f"{saved.name} saved as a draft.")
            return redirect("portal:plans")
    else:
        initial = {}
        trend_id = request.GET.get("trend")
        if trend_id:
            trend = MarketTrend.objects.filter(pk=trend_id).first()
            if trend:
                # Seed the form from the trend the lead clicked.
                initial = {
                    "name": f"{trend.product} push",
                    "product": trend.product,
                    "category": trend.category,
                    "rationale": (
                        f"{trend.product} is {trend.direction} {abs(trend.change_pct)}% "
                        f"in {trend.region} with only {trend.attach_rate}% attach. "
                        f"A per-unit incentive should close that gap."
                    ),
                    "runs_from": timezone.localdate(),
                    "runs_to": timezone.localdate() + timezone.timedelta(days=30),
                }
        form = PlanForm(instance=plan, agent=agent, initial=initial)

    return render(request, "portal/plan_form.html", {
        "form": form,
        "plan": plan,
        "active_nav": "plans",
    })


@role_required(RoleType.LEAD, RoleType.MANAGER)
def plan_submit(request, plan_id):
    """Send a draft to the manager."""
    agent = request.user.agent
    plan = get_object_or_404(IncentivePlan, pk=plan_id, created_by=agent)
    if request.method == "POST" and plan.is_editable:
        plan.status = IncentivePlan.State.SUBMITTED
        plan.save(update_fields=["status"])
        messages.success(request, f"{plan.name} sent for approval.")
    return redirect("portal:plans")


@role_required(RoleType.MANAGER)
def plan_decide(request, plan_id):
    """Approve or reject. Only the manager who owns the plan's team may do this."""
    agent = request.user.agent
    plan = get_object_or_404(IncentivePlan, pk=plan_id)

    if not plan.can_be_decided_by(agent):
        raise PermissionDenied("That plan is not yours to decide.")

    if request.method == "POST":
        decision = request.POST.get("decision")
        if decision in ("approve", "reject"):
            plan.status = (IncentivePlan.State.APPROVED if decision == "approve"
                           else IncentivePlan.State.REJECTED)
            plan.decided_by = agent
            plan.decision_note = request.POST.get("note", "").strip()
            plan.save(update_fields=["status", "decided_by", "decision_note"])
            messages.success(
                request,
                f"{plan.name} {'approved' if decision == 'approve' else 'rejected'}.",
            )
    return redirect("portal:plans")


@role_required(RoleType.LEAD, RoleType.MANAGER)
def plan_clone(request, plan_id):
    """
    Copy a plan into a fresh draft, one version higher.

    A decided plan is never edited in place: what a manager approved has to
    stay exactly as approved, or the audit trail is worthless. Cloning is
    how you change a plan that has already been through the chain.
    """
    agent = request.user.agent
    plan = get_object_or_404(IncentivePlan, pk=plan_id)

    # You may clone anything you can see, but the copy is always yours.
    if plan.team not in agent.visible_teams:
        raise PermissionDenied("That plan is not yours to clone.")

    if request.method != "POST":
        return redirect("portal:plans")

    root = plan.cloned_from or plan
    family = IncentivePlan.objects.filter(
        models.Q(pk=root.pk) | models.Q(cloned_from=root))
    next_version = max((p.version for p in family), default=plan.version) + 1

    copy = IncentivePlan.objects.create(
        name=plan.name,
        rationale=plan.rationale,
        team=plan.team,
        product=plan.product,
        category=plan.category,
        reward_type=plan.reward_type,
        reward_amount=plan.reward_amount,
        target_units=plan.target_units,
        runs_from=plan.runs_from,
        runs_to=plan.runs_to,
        status=IncentivePlan.State.DRAFT,
        created_by=agent,
        version=next_version,
        cloned_from=root,
    )
    messages.success(
        request,
        f"{copy.name} copied as v{copy.version}. The original is unchanged.",
    )
    return redirect("portal:plan_edit", plan_id=copy.pk)


# --------------------------------------------------------------------------
# Assistant
# --------------------------------------------------------------------------


@login_required
def ask(request):
    """
    The in-portal assistant. Answers from the database, scoped to the role.

    History lives in the session so the conversation survives a reload without
    needing a table for what is throwaway text.
    """
    agent = getattr(request.user, "agent", None)
    history = request.session.get("ask_history", [])

    if request.method == "POST":
        if request.POST.get("clear"):
            request.session["ask_history"] = []
            return redirect("portal:ask")

        question = (request.POST.get("q") or "").strip()[:300]
        if question:
            text, links, engine = assistant.respond(agent, question, history=history)
            history.append({
                "q": question,
                "a": text,
                "engine": engine,
                "links": [{"label": lab, "url": reverse(name)} for lab, name in links],
            })
            request.session["ask_history"] = history[-12:]
        return redirect("portal:ask")

    return render(request, "portal/ask.html", {
        "history": history,
        "suggestions": assistant.SUGGESTIONS.get(
            agent.role_type if agent else None, []),
        "llm_on": llm.is_configured(),
        "active_nav": "ask",
    })


@login_required
def ask_api(request):
    """
    JSON endpoint behind the floating assistant, so asking a question does
    not reload the page. Same engine and the same session history as /ask/.
    """
    from django.http import JsonResponse

    agent = getattr(request.user, "agent", None)
    history = request.session.get("ask_history", [])

    if request.method != "POST":
        return JsonResponse({"history": history})

    if request.POST.get("clear"):
        request.session["ask_history"] = []
        return JsonResponse({"history": [], "cleared": True})

    question = (request.POST.get("q") or "").strip()[:300]
    if not question:
        return JsonResponse({"error": "Ask me something about your numbers."}, status=400)

    text, links, engine = assistant.respond(agent, question, history=history)
    turn = {
        "q": question,
        "a": text,
        "engine": engine,
        "links": [{"label": lab, "url": reverse(name)} for lab, name in links],
    }
    history.append(turn)
    request.session["ask_history"] = history[-12:]
    return JsonResponse(turn)
