from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import (
    AgentProfile,
    Team,
    Incentive,
    Persona,
    Product,
    Spec,
    SpecGroup,
)


# --------------------------------------------------------------------------
# Sign in - POC role picker, no credentials
# --------------------------------------------------------------------------
def _portal_stats():
    """Aggregate stats for the sign-in hero panel."""
    return {
        "stat_incentives": Incentive.objects.exclude(bucket="previous").count(),
        "stat_products": Product.objects.count(),
        "stat_specs": Spec.objects.count(),
        "stat_agents": AgentProfile.objects.count(),
        "stat_teams": Team.objects.count(),
        "stat_people": AgentProfile.objects.count(),
    }


def role_select(request):
    """
    The sign-in screen: pick a demo role, no password.

    POSTing a persona slug logs you straight in as that persona's user. This is
    deliberately passwordless because it is a POC demo, so it is fenced in:
    the view 404s unless settings.PORTAL_DEMO_LOGIN is on, and only personas
    flagged `is_available` can be entered.
    """
    if not getattr(settings, "PORTAL_DEMO_LOGIN", False):
        raise Http404("Demo sign-in is disabled.")

    if request.user.is_authenticated:
        return redirect("portal:dashboard")

    personas = Persona.objects.select_related("user")
    grouped = [
        ("Managers", [p for p in personas if p.role_type == "manager"]),
        ("Team Leads", [p for p in personas if p.role_type == "lead"]),
        ("Field Agents", [p for p in personas if p.role_type == "agent"]),
    ]
    error = None

    if request.method == "POST":
        persona = Persona.objects.filter(
            slug=request.POST.get("persona"), is_available=True, user__isnull=False
        ).select_related("user").first()

        if persona is None:
            error = "That role is not part of this POC yet. Pick the Residential Inbound Agent."
        else:
            # No password is checked - the persona itself is the credential.
            login(request, persona.user, backend="django.contrib.auth.backends.ModelBackend")
            agent = getattr(persona.user, "agent", None)
            if agent:
                request.session["signin_reward"] = agent.register_signin(
                    timezone.localdate()
                )
            return redirect(request.POST.get("next") or "portal:dashboard")

    # Open on a field agent: it is the richest view and the demo's starting point.
    default = next((p for p in personas if p.role_type == "agent"), None)

    ctx = {"personas": personas, "grouped": grouped, "error": error,
           "default_slug": default.slug if default else "",
           "next": request.GET.get("next", "")}
    ctx.update(_portal_stats())
    return render(request, "registration/login.html", ctx)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _agent(request):
    """The signed-in user's agent profile, or None if they have no profile."""
    return getattr(request.user, "agent", None)


def _filtered(queryset, request, categories, cat_attr="category"):
    """
    Apply the ?cat= chip and ?q= search shared by the offers, products and
    incentives pages.

    Every item is returned, each flagged with `.is_hidden`, rather than the
    non-matches being dropped. The template renders the full set so the
    client-side filter can show and hide instantly with no round trip; with
    JavaScript disabled the server-rendered `hidden` attribute still gives
    correct results.
    """
    cat = request.GET.get("cat", "All")
    query = request.GET.get("q", "").strip()
    if cat not in categories:
        cat = "All"

    needle = query.lower()
    items = list(queryset)
    visible = 0
    for item in items:
        matches_cat = cat == "All" or getattr(item, cat_attr) == cat
        matches_query = not needle or needle in item.search_blob
        item.is_hidden = not (matches_cat and matches_query)
        if not item.is_hidden:
            visible += 1

    return items, cat, query, visible


CATEGORY_CHIPS = {
    "offers": ["Internet", "Mobile", "TV", "Voice", "Bundle", "Business", "Add-on"],
    "products": ["Internet", "Mobile", "TV", "Voice", "Business", "Equipment"],
}


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@login_required
def product_list(request):
    chips = CATEGORY_CHIPS["products"]
    qs = Product.objects.prefetch_related(
        "highlights", Prefetch("spec_groups", queryset=SpecGroup.objects.prefetch_related("specs"))
    )
    products, cat, query, visible = _filtered(qs, request, chips)

    return render(
        request,
        "portal/products.html",
        {
            "products": products,
            "all_products": Product.objects.prefetch_related("highlights"),
            "chips": chips,
            "cat": cat,
            "query": query,
            "visible": visible,
            "active_nav": "products",
        },
    )


@login_required
def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.prefetch_related(
            "highlights",
            "links",
            Prefetch("spec_groups", queryset=SpecGroup.objects.prefetch_related("specs")),
        ),
        slug=slug,
    )
    return render(
        request,
        "portal/product_detail.html",
        {
            "product": product,
            "active_nav": "products",
        },
    )


