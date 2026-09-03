from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse


class Status(models.TextChoices):
    ACTIVE = "active", "Active"
    ENDING = "ending", "Ending soon"
    EXPIRED = "expired", "Expired"
    AT_RISK = "at-risk", "At risk"


BADGE_CLASS = {
    Status.ACTIVE: "green",
    Status.ENDING: "amber",
    Status.EXPIRED: "grey",
    Status.AT_RISK: "red",
}


class RoleType(models.TextChoices):
    """The three levels of the sales hierarchy."""

    AGENT = "agent", "Field Agent"
    LEAD = "lead", "Team Lead"
    MANAGER = "manager", "Manager"


class Category(models.TextChoices):
    INTERNET = "Internet", "Internet"
    MOBILE = "Mobile", "Mobile"
    TV = "TV", "TV"
    VOICE = "Voice", "Voice"
    BUNDLE = "Bundle", "Bundle"
    BUSINESS = "Business", "Business"
    ADDON = "Add-on", "Add-on"
    EQUIPMENT = "Equipment", "Equipment"


# --------------------------------------------------------------------------
# Org structure
# --------------------------------------------------------------------------
class Team(models.Model):
    """A squad of field agents under one team lead."""

    name = models.CharField(max_length=60, unique=True)
    region = models.CharField(max_length=60, blank=True)
    lead = models.ForeignKey(
        "AgentProfile", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="teams_led",
    )
    manager = models.ForeignKey(
        "AgentProfile", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="teams_managed",
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    @property
    def agents(self):
        return self.members.filter(role_type=RoleType.AGENT)

    # ---- rollups, computed from the members rather than stored ----
    @property
    def total_points(self):
        return sum(a.scorecard.total_points for a in self.agents if hasattr(a, "scorecard"))

    @property
    def headcount(self):
        return self.agents.count()

    @property
    def attainment(self):
        """Mean quota attainment across the team, as a percentage."""
        values = [a.attainment for a in self.agents]
        return round(sum(values) / len(values)) if values else 0

    @property
    def open_disputes(self):
        return Dispute.objects.filter(
            agent__team=self, status__in=Dispute.OPEN_STATES
        ).count()

    @property
    def bar_class(self):
        if self.attainment >= 100:
            return "green"
        return "amber" if self.attainment < 70 else ""


# --------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------
class AgentProfile(models.Model):
    """Sales-specific fields hung off the Django user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent"
    )
    agent_id = models.CharField(max_length=20, unique=True)
    role = models.CharField(max_length=80, default="Sales Agent")
    role_type = models.CharField(
        max_length=10, choices=RoleType.choices, default=RoleType.AGENT,
        help_text="Drives what this person can see",
    )
    team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="members"
    )
    channel = models.CharField(max_length=80, blank=True)
    market = models.CharField(max_length=80, blank=True)
    manager = models.CharField(max_length=80, blank=True)
    tier = models.CharField(max_length=30, blank=True)
    agent_since = models.CharField(max_length=40, blank=True)

    # --- progression, shown on the sign-in screen and the dashboard ---
    department = models.CharField(max_length=60, blank=True)
    supervisor = models.CharField(max_length=60, blank=True)
    points_balance = models.PositiveIntegerField(default=0, help_text="Spendable reward points")

    xp = models.PositiveIntegerField(default=0, help_text="Lifetime experience points")
    streak_days = models.PositiveIntegerField(default=0, help_text="Consecutive days signed in")

    class Presents(models.TextChoices):
        WOMAN = "woman", "Woman"
        MAN = "man", "Man"
        UNSPECIFIED = "unspecified", "Prefer not to say"

    # Stored, never guessed. Inferring this from a first name misgenders
    # real people; it is recorded per person and used only to choose which
    # variant of the assistant character greets them.
    presents_as = models.CharField(
        max_length=12, choices=Presents.choices, default=Presents.UNSPECIFIED,
        help_text="Chooses the assistant character's appearance for this person",
    )
    last_seen = models.DateField(null=True, blank=True)
    last_roll_face = models.PositiveSmallIntegerField(default=0)
    last_roll_on = models.DateField(null=True, blank=True)

    XP_PER_LEVEL = 500
    RANK_TITLES = [
        (20, "Legend"),
        (15, "Elite Closer"),
        (10, "Specialist"),
        (5, "Closer"),
        (0, "Rookie"),
    ]

    class Meta:
        ordering = ["agent_id"]

    def __str__(self):
        return f"{self.agent_id} - {self.full_name}"

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def first_name(self):
        return self.user.first_name or self.user.username

    @property
    def initials(self):
        parts = [p for p in self.full_name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "AG"

    # ---- progression maths -------------------------------------------
    @property
    def level(self):
        return self.xp // self.XP_PER_LEVEL + 1

    @property
    def xp_into_level(self):
        return self.xp % self.XP_PER_LEVEL

    @property
    def xp_for_next_level(self):
        return self.XP_PER_LEVEL

    @property
    def level_pct(self):
        return round(self.xp_into_level / self.XP_PER_LEVEL * 100)

    @property
    def xp_to_next_level(self):
        return self.XP_PER_LEVEL - self.xp_into_level

    @property
    def rank_title(self):
        for threshold, title in self.RANK_TITLES:
            if self.level >= threshold:
                return title
        return "Rookie"

    # ---- hierarchy ---------------------------------------------------
    @property
    def is_agent(self):
        return self.role_type == RoleType.AGENT

    @property
    def is_lead(self):
        return self.role_type == RoleType.LEAD

    @property
    def is_manager(self):
        return self.role_type == RoleType.MANAGER

    @property
    def can_see_team(self):
        """Leads and managers both get team views."""
        return self.role_type in (RoleType.LEAD, RoleType.MANAGER)

    @property
    def visible_teams(self):
        """Teams this person is responsible for."""
        if self.is_manager:
            return Team.objects.filter(manager=self)
        if self.is_lead:
            return Team.objects.filter(lead=self)
        return Team.objects.none()

    @property
    def visible_agents(self):
        """Every field agent below this person in the hierarchy."""
        if self.is_agent:
            return AgentProfile.objects.filter(pk=self.pk)
        return AgentProfile.objects.filter(
            team__in=self.visible_teams, role_type=RoleType.AGENT
        ).select_related("team", "scorecard")

    @property
    def attainment(self):
        """Quota attainment across this agent's own quota rows."""
        rows = list(self.quotas.all())
        if not rows:
            return 0
        return round(sum(r.pct for r in rows) / len(rows))

    @property
    def attainment_class(self):
        if self.attainment >= 100:
            return "green"
        return "amber" if self.attainment < 70 else ""

    DIE_FACES = 6
    XP_PER_PIP = 10

    def roll_the_die(self, today=None):
        """
        Roll the die and bank the XP: the face, times ten.

        Decided here rather than in the browser - a roll worth XP the client
        controls is not a roll.

        The first roll of a day pays. Signing in again the same day shows the
        face you already rolled and pays nothing, so the die is always there
        to look at but cannot be farmed by signing out and back in.

        Returns (xp_awarded, face).
        """
        import secrets

        if today is not None and self.last_roll_on == today:
            return 0, self.last_roll_face or 1

        face = secrets.randbelow(self.DIE_FACES) + 1   # 1..6, unbiased
        xp = face * self.XP_PER_PIP
        self.xp += xp
        self.last_roll_face = face
        if today is not None:
            self.last_roll_on = today
        self.save(update_fields=["xp", "last_roll_face", "last_roll_on"])
        return xp, face

    def register_signin(self, today):
        """
        Bump the login streak. Returns a dict describing what changed, so the
        sign-in transition can show it.

        Same day  -> nothing changes.
        Yesterday -> streak continues.
        Older/none-> streak resets to 1.
        """
        from datetime import timedelta

        previous_streak = self.streak_days
        previous_level = self.level

        if self.last_seen == today:
            awarded = 0
        else:
            if self.last_seen == today - timedelta(days=1):
                self.streak_days += 1
            else:
                self.streak_days = 1
            # 25 XP for showing up, +5 per streak day, capped at 100.
            awarded = min(100, 25 + 5 * self.streak_days)
            self.xp += awarded
            self.last_seen = today
            self.save(update_fields=["xp", "streak_days", "last_seen"])

        # The daily roll. Server-side so the face cannot be chosen in the
        # browser, and only on a day they have not already been given one -
        # otherwise signing out and back in farms XP without limit.
        roll = die = 0
        already_rolled = self.last_roll_on == today
        if self.is_agent:
            roll, die = self.roll_the_die(today)

        return {
            "xp_awarded": awarded,
            "die": die,
            "die_xp": roll,
            "die_already_rolled": already_rolled,
            "total_xp": awarded + roll,
            "streak_days": self.streak_days,
            "streak_continued": self.streak_days > previous_streak,
            "levelled_up": self.level > previous_level,
            "level": self.level,
        }


class Quota(models.Model):
    """Monthly unit target for one line of business."""

    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name="quotas")
    lob = models.CharField("line of business", max_length=40)
    sold = models.PositiveIntegerField(default=0)
    target = models.PositiveIntegerField(default=1)
    unit = models.CharField(max_length=20, default="units")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "lob"]

    def __str__(self):
        return f"{self.lob}: {self.sold}/{self.target}"

    @property
    def pct(self):
        return min(100, round(self.sold / self.target * 100)) if self.target else 0

    @property
    def bar_class(self):
        if self.sold >= self.target:
            return "green"
        return "amber" if self.pct < 60 else ""


class PerformanceSnapshot(models.Model):
    """One cycle of headline numbers for an agent."""

    agent = models.ForeignKey(
        AgentProfile, on_delete=models.CASCADE, related_name="snapshots"
    )
    period = models.CharField(max_length=40, help_text="e.g. August 2026")
    days_left = models.PositiveSmallIntegerField(default=0)
    units_sold = models.PositiveIntegerField(default=0)
    unit_target = models.PositiveIntegerField(default=1)
    gross_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    spiff_earned = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pending_payout = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    next_payout_date = models.CharField(max_length=40, blank=True)
    last_month_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    close_rate = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    chargebacks = models.PositiveSmallIntegerField(default=0)
    chargeback_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rank = models.PositiveSmallIntegerField(default=0)
    rank_of = models.PositiveSmallIntegerField(default=0)
    ytd_earned = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_current = models.BooleanField(default=True)

    # --- inbound-queue metrics ---
    calls_handled = models.PositiveIntegerField(default=0)
    calls_converted = models.PositiveIntegerField(default=0)
    avg_handle_time = models.CharField(max_length=10, blank=True, help_text="mm:ss")
    attach_rate = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    queue_position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-is_current", "-id"]

    def __str__(self):
        return f"{self.agent.agent_id} - {self.period}"

    @property
    def unit_pct(self):
        return min(100, round(self.units_sold / self.unit_target * 100)) if self.unit_target else 0

    @property
    def total_earned(self):
        return self.gross_commission + self.spiff_earned

    @property
    def month_over_month(self):
        """Percent change in commission vs the prior month."""
        if not self.last_month_commission:
            return None
        delta = self.gross_commission - self.last_month_commission
        return (delta / self.last_month_commission * 100).quantize(Decimal("0.1"))

    @property
    def conversion_rate(self):
        """Share of handled inbound calls that closed a sale."""
        if not self.calls_handled:
            return Decimal("0.0")
        return (Decimal(self.calls_converted) / self.calls_handled * 100).quantize(
            Decimal("0.1")
        )


# --------------------------------------------------------------------------
# Demo personas (POC sign-in)
# --------------------------------------------------------------------------
class Persona(models.Model):
    """
    A selectable demo role on the sign-in screen.

    This POC signs in without credentials: picking a persona logs you straight
    in as its user. Only personas with `is_available` can be entered, and the
    whole flow is gated behind settings.PORTAL_DEMO_LOGIN so it cannot be
    switched on by accident outside the demo.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="persona",
        null=True,
        blank=True,
    )
    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    title = models.CharField(max_length=120)
    blurb = models.CharField(max_length=200, help_text="What this role can do")
    accent = models.CharField(max_length=20, default="blue")
    role_type = models.CharField(
        max_length=10, choices=RoleType.choices, default=RoleType.AGENT,
        help_text="Groups the picker on the sign-in screen",
    )
    is_available = models.BooleanField(
        default=False, help_text="Unchecked roles show on the picker but cannot be entered"
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.name} - {self.title}"

    @property
    def initials(self):
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "??"


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------
class Product(models.Model):
    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=40)
    category = models.CharField(max_length=20, choices=Category.choices)
    icon = models.CharField(max_length=8, default="\U0001F4E6", help_text="Emoji shown on the card")
    description = models.TextField()
    price_note = models.CharField(max_length=120, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("portal:product_detail", args=[self.slug])

    @property
    def search_blob(self):
        """Everything a product search should match against, including spec text."""
        bits = [self.name, self.sku, self.category, self.description]
        for group in self.spec_groups.all():
            bits.append(group.name)
            bits += [f"{s.label} {s.value}" for s in group.specs.all()]
        return " ".join(bits).lower()


class Highlight(models.Model):
    """The two or three at-a-glance rows on a product card."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="highlights")
    label = models.CharField(max_length=40)
    value = models.CharField(max_length=80)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.label}: {self.value}"


class SpecGroup(models.Model):
    """A section of the spec sheet, e.g. Performance / Network / Equipment."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="spec_groups")
    name = models.CharField(max_length=60)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.product.name} / {self.name}"


class Spec(models.Model):
    group = models.ForeignKey(SpecGroup, on_delete=models.CASCADE, related_name="specs")
    label = models.CharField(max_length=80)
    value = models.CharField(max_length=255)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.label}: {self.value}"


class ProductLink(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="links")
    label = models.CharField(max_length=80)
    url = models.CharField(max_length=300, default="#")
    icon = models.CharField(max_length=8, default="\U0001F517")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.label

    @property
    def is_external(self):
        return self.url.startswith("http")


# --------------------------------------------------------------------------
# Offers
# --------------------------------------------------------------------------
class Offer(models.Model):
    code = models.CharField(max_length=20, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=Category.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    badges = models.CharField(
        max_length=120, blank=True, help_text="Comma-separated, e.g. Best seller, High payout"
    )
    blurb = models.TextField()
    points = models.TextField(help_text="One selling point per line")

    price = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    price_period = models.CharField(max_length=40, blank=True, help_text="e.g. /mo for 12 mos")
    was_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    commission = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    spiff = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    spiff_note = models.CharField(max_length=160, blank=True)

    eligibility = models.TextField(blank=True)
    terms = models.TextField(blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    products = models.ManyToManyField(Product, related_name="offers", blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    @property
    def total_payout(self):
        return self.commission + self.spiff

    @property
    def badge_list(self):
        return [b.strip() for b in self.badges.split(",") if b.strip()]

    @property
    def point_list(self):
        return [p.strip() for p in self.points.splitlines() if p.strip()]

    @property
    def status_class(self):
        return BADGE_CLASS.get(self.status, "grey")

    @property
    def is_credit_offer(self):
        return self.price <= 0

    @property
    def search_blob(self):
        return " ".join(
            [self.name, self.blurb, self.category, self.points, self.spiff_note]
        ).lower()


# --------------------------------------------------------------------------
# Incentives
# --------------------------------------------------------------------------
class Incentive(models.Model):
    class Kind(models.TextChoices):
        SPIFF = "SPIFF", "SPIFF"
        TIERED = "Tiered bonus", "Tiered bonus"
        MULTIPLIER = "Multiplier", "Multiplier"
        QUALITY = "Quality bonus", "Quality bonus"
        RECOGNITION = "Recognition", "Recognition"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField("type", max_length=20, choices=Kind.choices, default=Kind.SPIFF)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    payout = models.CharField(max_length=120, help_text="e.g. $75 per bundle sale")
    period = models.CharField(max_length=60, help_text="e.g. Aug 1 - Sep 15, 2026")
    description = models.TextField()

    progress = models.PositiveIntegerField(default=0)
    goal = models.PositiveIntegerField(default=1)
    unit = models.CharField(max_length=30, default="sales")
    earned = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    potential = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    offers = models.ManyToManyField(Offer, related_name="incentives", blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    # --- incentive-feed fields ---
    short_code = models.CharField(max_length=12, blank=True, help_text="e.g. Inc 01")
    points_earned = models.PositiveIntegerField(default=0)
    rate_per_unit = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    unit_rate_label = models.CharField(max_length=40, blank=True, help_text="e.g. $10/unit")
    days_left = models.PositiveSmallIntegerField(default=0)
    is_points_based = models.BooleanField(default=False)
    bucket = models.CharField(
        max_length=16, default="active",
        choices=[("active", "Active"), ("launched", "Just Launched"),
                 ("ending", "Ending Soon"), ("previous", "Previous")],
    )

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    @property
    def pct(self):
        return min(100, round(self.progress / self.goal * 100)) if self.goal else 0

    @property
    def status_class(self):
        return BADGE_CLASS.get(self.status, "grey")

    @property
    def bar_class(self):
        if self.status == Status.AT_RISK:
            return "amber"
        return "green" if self.pct >= 100 else ""

    @property
    def remaining(self):
        return max(Decimal("0.00"), self.potential - self.earned)

    @property
    def search_blob(self):
        return " ".join([self.name, self.kind, self.description, self.payout, self.period]).lower()


# --------------------------------------------------------------------------
# Sales
# --------------------------------------------------------------------------
class Sale(models.Model):
    class SaleStatus(models.TextChoices):
        INSTALLED = "Installed", "Installed"
        ACTIVE = "Active", "Active"
        PENDING = "Pending install", "Pending install"
        SCHEDULED = "Scheduled", "Scheduled"
        CHARGEBACK = "Chargeback", "Chargeback"

    TONE = {
        SaleStatus.INSTALLED: "green",
        SaleStatus.ACTIVE: "green",
        SaleStatus.PENDING: "amber",
        SaleStatus.SCHEDULED: "amber",
        SaleStatus.CHARGEBACK: "red",
    }

    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name="sales")
    sold_on = models.DateField()
    order_no = models.CharField(max_length=30, unique=True)
    customer = models.CharField(max_length=120)
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name="sales")
    units = models.PositiveSmallIntegerField(default=1)
    base = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    spiff = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=SaleStatus.choices, default=SaleStatus.PENDING)

    # ---- incentive approval ----------------------------------------
    # A sale logged by an agent does not earn its incentive until the
    # agent's own team lead signs it off. Seeded history defaults to
    # APPROVED so existing figures are unchanged.
    class Approval(models.TextChoices):
        AWAITING_LEAD = "Awaiting lead", "Awaiting team lead"
        APPROVED = "Approved", "Incentive approved"
        REJECTED = "Rejected", "Rejected by lead"

    APPROVAL_TONE = {
        Approval.AWAITING_LEAD: "amber",
        Approval.APPROVED: "green",
        Approval.REJECTED: "red",
    }

    approval = models.CharField(
        max_length=20, choices=Approval.choices, default=Approval.APPROVED
    )
    decided_by = models.ForeignKey(
        AgentProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sales_decided",
    )
    decision_note = models.CharField(max_length=200, blank=True)
    decided_on = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-sold_on", "-order_no"]

    def __str__(self):
        return f"{self.order_no} - {self.customer}"

    @property
    def approval_class(self):
        return self.APPROVAL_TONE.get(self.approval, "")

    @property
    def is_awaiting_decision(self):
        return self.approval == self.Approval.AWAITING_LEAD

    @property
    def incentive_value(self):
        """What the agent earns from this sale, once it is approved."""
        return self.base + self.spiff

    @property
    def earned(self):
        """Only an approved sale actually pays."""
        if self.approval == self.Approval.APPROVED:
            return self.incentive_value
        return Decimal("0.00")

    def can_be_decided_by(self, approver):
        """
        Only the lead of the agent's own team may sign a sale off, and only
        while it is still awaiting a decision. Mirrors Dispute.
        """
        if approver is None or not self.is_awaiting_decision:
            return False
        team = self.agent.team
        if team is None:
            return False
        if approver.is_lead:
            return team.lead_id == approver.pk
        if approver.is_manager:
            return team.manager_id == approver.pk
        return False

    @property
    def total(self):
        return self.base + self.spiff

    @property
    def status_class(self):
        return self.TONE.get(self.status, "grey")


# --------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------
class Announcement(models.Model):
    TONES = [("", "Neutral"), ("amber", "Amber"), ("red", "Red"), ("green", "Green")]

    posted_on = models.DateField()
    tag = models.CharField(max_length=30)
    tone = models.CharField(max_length=10, blank=True, choices=TONES)
    text = models.TextField()

    class Meta:
        ordering = ["-posted_on", "-id"]

    def __str__(self):
        return f"{self.tag}: {self.text[:50]}"


class Resource(models.Model):
    icon = models.CharField(max_length=8, default="\U0001F517")
    label = models.CharField(max_length=80)
    meta = models.CharField(max_length=60, blank=True)
    url = models.CharField(max_length=300, default="#")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "label"]

    def __str__(self):
        return self.label


class SupportContact(models.Model):
    label = models.CharField(max_length=80)
    value = models.CharField(max_length=120)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.label}: {self.value}"


class Cutoff(models.Model):
    label = models.CharField(max_length=80)
    value = models.CharField(max_length=120)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.label}: {self.value}"


# ==========================================================================
# Incentive-portal domain (matches the reference POC)
# ==========================================================================
class Period(models.Model):
    """A selectable month in the header dropdown."""

    label = models.CharField(max_length=20, unique=True, help_text="e.g. August 2026")
    starts_on = models.DateField()
    is_current = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.label


class Tier(models.Model):
    """Contender / Contributor / Achiever / Star."""

    name = models.CharField(max_length=40, unique=True)
    threshold_points = models.PositiveIntegerField()
    payout = models.DecimalField(max_digits=9, decimal_places=2)
    next_label = models.CharField(
        max_length=20, blank=True,
        help_text='Plan-defined step to this tier, e.g. "Next 180" or "Top 33"',
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.name} ({self.threshold_points} pts)"


class PointsRule(models.Model):
    """The points structure: how many points each PSU type is worth."""

    label = models.CharField(max_length=60, help_text="e.g. Gig Internet PSU")
    short_label = models.CharField(max_length=12, blank=True, help_text="e.g. GIG")
    points = models.PositiveSmallIntegerField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.label} - {self.points} pts"


class Badge(models.Model):
    """Achievement badges shown on the home page, per agent."""

    agent = models.ForeignKey(
        AgentProfile, on_delete=models.CASCADE, related_name="badges",
        null=True, blank=True,
    )
    name = models.CharField(max_length=40)
    icon = models.CharField(max_length=8, default="\U0001F3C5")
    description = models.CharField(max_length=120, blank=True)
    is_earned = models.BooleanField(default=False)
    is_milestone = models.BooleanField(
        default=False, help_text="Counts toward the second badge tally"
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("agent", "name")]

    def __str__(self):
        return self.name


class TrendPoint(models.Model):
    """One bar on the monthly earnings trend chart."""

    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name="trend")
    month = models.CharField(max_length=10, help_text="e.g. Jan")
    amount = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.month}: {self.amount}"


class MtdCategory(models.Model):
    """Month-to-date volume and points for one PSU category."""

    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name="mtd")
    label = models.CharField(max_length=20, help_text="e.g. GIG, INT PSU, VID PSU")
    volume = models.PositiveIntegerField(default=0)
    points = models.PositiveIntegerField(default=0)
    pct_of_points = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    star_pct = models.DecimalField(
        max_digits=5, decimal_places=1, default=0,
        help_text="What a Star-tier rep does in this category",
    )
    is_focus = models.BooleanField(default=False, help_text="Best improvement opportunity")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name_plural = "MTD categories"

    def __str__(self):
        return f"{self.label}: {self.volume} units / {self.points} pts"

    @property
    def difference(self):
        """How far behind (or ahead of) a Star rep this category is."""
        return self.pct_of_points - self.star_pct

    @property
    def difference_class(self):
        return "down" if self.difference < 0 else "up"


class Scorecard(models.Model):
    """The agent standing in the current incentive - the detail page header."""

    agent = models.OneToOneField(
        AgentProfile, on_delete=models.CASCADE, related_name="scorecard"
    )
    psid = models.CharField(max_length=20, help_text="e.g. EMP-78432")
    job_code = models.CharField(max_length=20, help_text="e.g. AE-INB")
    location = models.CharField(max_length=60, help_text="e.g. Southwest Region")
    incentive_id = models.CharField(max_length=30, help_text="e.g. RIBSR2606ACQ")

    rank = models.PositiveIntegerField(default=0)
    previous_rank = models.PositiveIntegerField(default=0, help_text="Last period, for movement arrows")
    rank_of = models.PositiveIntegerField(default=0)
    total_points = models.PositiveIntegerField(default=0)
    current_tier = models.ForeignKey(
        Tier, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    potential_payout = models.DecimalField(max_digits=9, decimal_places=2, default=0)

    point_streak = models.PositiveSmallIntegerField(
        default=0, help_text="Consecutive days scoring points"
    )
    period_days = models.PositiveSmallIntegerField(default=31)
    days_remaining = models.PositiveSmallIntegerField(default=0)

    eligibility = models.CharField(max_length=30, default="Eligible")
    report_date = models.DateField(null=True, blank=True)
    finalization_date = models.DateField(null=True, blank=True)
    pay_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Scorecard for {self.agent.agent_id}"

    @property
    def top_pct(self):
        """Powers the "you are in the top N%" line - derived, not stored."""
        if not self.rank_of:
            return 0
        return max(1, round(self.rank / self.rank_of * 100))

    @property
    def streak_pct(self):
        return round(self.point_streak / self.period_days * 100) if self.period_days else 0

    @property
    def streak_dots(self):
        """One dot per day in the period, lit for days already scored."""
        return [i < self.point_streak for i in range(self.period_days)]

    @property
    def rank_delta(self):
        """Positions gained since last period. Positive is an improvement."""
        if not self.previous_rank:
            return 0
        return self.previous_rank - self.rank

    @property
    def rank_direction(self):
        delta = self.rank_delta
        return "up" if delta > 0 else ("down" if delta < 0 else "flat")


class Dispute(models.Model):
    """A payout dispute ticket."""

    class Category(models.TextChoices):
        COMMISSION = "Commission Error", "Commission Error"
        BONUS = "Bonus / SPIF Not Applied", "Bonus / SPIF Not Applied"
        CLAWBACK = "Clawback Dispute", "Clawback Dispute"
        MISSING = "Missing Payout", "Missing Payout"

    class Priority(models.TextChoices):
        HIGH = "High", "High"
        MEDIUM = "Medium", "Medium"
        LOW = "Low", "Low"

    class State(models.TextChoices):
        # An agent raises a dispute; their team lead signs it off before it
        # goes anywhere. Same shape as a lead's plan needing their manager.
        AWAITING_LEAD = "Awaiting lead", "Awaiting team lead"
        IN_REVIEW = "In Review", "Approved - with payouts"
        RESOLVED = "Resolved", "Resolved"
        REJECTED = "Rejected", "Rejected by lead"

    TONE = {
        State.AWAITING_LEAD: "amber",
        State.IN_REVIEW: "",
        State.RESOLVED: "green",
        State.REJECTED: "red",
    }

    OPEN_STATES = [State.AWAITING_LEAD, State.IN_REVIEW]
    PRIORITY_TONE = {Priority.HIGH: "red", Priority.MEDIUM: "amber", Priority.LOW: "grey"}

    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name="disputes")
    ticket_no = models.CharField(max_length=20, unique=True, help_text="e.g. TKT-00001")
    subject = models.CharField(max_length=160)
    category = models.CharField(max_length=40, choices=Category.choices)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(
        max_length=14, choices=State.choices, default=State.AWAITING_LEAD
    )
    detail = models.TextField(blank=True)
    raised_on = models.DateField(null=True, blank=True)

    decided_by = models.ForeignKey(
        "AgentProfile", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="disputes_decided",
    )
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-raised_on", "-id"]

    def __str__(self):
        return f"{self.ticket_no} - {self.subject}"

    @classmethod
    def next_ticket_no(cls):
        """TKT-00001, TKT-00002, ... Derived so numbers never collide."""
        last = cls.objects.order_by("-id").first()
        try:
            n = int(last.ticket_no.split("-")[-1]) + 1 if last else 1
        except (ValueError, AttributeError):
            n = cls.objects.count() + 1
        return f"TKT-{n:05d}"

    @property
    def status_class(self):
        return self.TONE.get(self.status, "grey")

    @property
    def priority_class(self):
        return self.PRIORITY_TONE.get(self.priority, "grey")

    @property
    def is_awaiting_decision(self):
        return self.status == self.State.AWAITING_LEAD

    def can_be_decided_by(self, approver):
        """
        The person one level above the agent signs this off: their team lead,
        or the manager who owns that team.
        """
        if approver is None or not self.is_awaiting_decision:
            return False
        team = self.agent.team
        if team is None:
            return False
        if approver.is_lead:
            return team.lead_id == approver.pk
        if approver.is_manager:
            return team.manager_id == approver.pk
        return False

    @property
    def search_blob(self):
        return " ".join([self.ticket_no, self.subject, self.category,
                         self.priority, self.status]).lower()


class Notification(models.Model):
    """Header notification tray."""

    kind = models.CharField(max_length=40, help_text="e.g. Exception Flagged")
    text = models.CharField(max_length=240)
    ago = models.CharField(max_length=20, help_text="e.g. 2m ago")
    tone = models.CharField(max_length=10, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.kind}: {self.text[:40]}"


class SavedPlan(models.Model):
    """A target the agent saved in the earnings calculator."""

    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name="plans")
    incentive = models.ForeignKey(Incentive, on_delete=models.CASCADE, related_name="plans")
    target_amount = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    target_tier = models.ForeignKey(
        Tier, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    units_needed = models.PositiveIntegerField(default=0)
    daily_target = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.incentive.name} - {self.target_amount or self.target_tier}"


class Quest(models.Model):
    """
    A daily objective worth XP. Completing one is the main moment-to-moment
    game loop, so it is a real record rather than a client-side toggle.
    """

    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name="quests")
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=160, blank=True)
    icon = models.CharField(max_length=8, default="\U0001F3AF")
    xp = models.PositiveSmallIntegerField(default=25)
    progress = models.PositiveIntegerField(default=0)
    goal = models.PositiveIntegerField(default=1)
    completed = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.progress}/{self.goal})"

    @property
    def pct(self):
        return min(100, round(self.progress / self.goal * 100)) if self.goal else 0

    @property
    def is_claimable(self):
        """Goal reached but the XP has not been taken yet."""
        return self.progress >= self.goal and not self.completed

    def claim(self):
        """Award the XP once. Returns the XP granted, or 0."""
        if self.completed or self.progress < self.goal:
            return 0
        self.completed = True
        self.save(update_fields=["completed"])
        self.agent.xp += self.xp
        self.agent.save(update_fields=["xp"])
        return self.xp


# ==========================================================================
# Market intelligence and plan approval
# ==========================================================================
class MarketTrend(models.Model):
    """
    What customers in a region are actually buying this period.

    Drives the trends page and seeds the plan builder's suggestions.
    """

    region = models.CharField(max_length=60)
    product = models.CharField(max_length=80)
    category = models.CharField(max_length=20, choices=Category.choices)
    units = models.PositiveIntegerField(default=0)
    change_pct = models.DecimalField(
        max_digits=5, decimal_places=1, default=0,
        help_text="Movement against last period",
    )
    attach_rate = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    period = models.CharField(max_length=40, default="August 2026")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["region", "order", "-units"]

    def __str__(self):
        return f"{self.region} - {self.product}: {self.units} units"

    @property
    def direction(self):
        if self.change_pct > 0:
            return "up"
        return "down" if self.change_pct < 0 else "flat"

    @property
    def is_opportunity(self):
        """Selling well but under-attached - the gap a SPIFF can close."""
        return self.change_pct > 0 and self.attach_rate < 50


class IncentivePlan(models.Model):
    """
    A proposed incentive, drafted by a team lead and approved by a manager.

    The status field is the whole workflow: draft -> submitted -> approved
    or rejected. Only a manager over the plan's team can decide it.
    """

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Awaiting approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    TONE = {
        State.DRAFT: "grey",
        State.SUBMITTED: "amber",
        State.APPROVED: "green",
        State.REJECTED: "red",
    }

    class Reward(models.TextChoices):
        CASH = "cash", "Cash per unit"
        POINTS = "points", "Points per unit"

    name = models.CharField(max_length=120)
    rationale = models.TextField(
        help_text="Why this plan, and which trend it responds to",
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="plans",
        help_text="Who the incentive is for",
    )
    product = models.CharField(max_length=80, help_text="What you want sold more of")
    category = models.CharField(max_length=20, choices=Category.choices)

    reward_type = models.CharField(max_length=10, choices=Reward.choices, default=Reward.CASH)
    reward_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    target_units = models.PositiveIntegerField(default=0)
    runs_from = models.DateField()
    runs_to = models.DateField()

    status = models.CharField(max_length=10, choices=State.choices, default=State.DRAFT)
    created_by = models.ForeignKey(
        AgentProfile, on_delete=models.CASCADE, related_name="plans_created"
    )
    decided_by = models.ForeignKey(
        AgentProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="plans_decided",
    )
    decision_note = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    # ---- versioning -------------------------------------------------
    # A decided plan is never edited: it is cloned into a new version, so
    # the thing a manager approved stays exactly as they approved it.
    version = models.PositiveSmallIntegerField(default=1)
    cloned_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="clones",
    )
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    @property
    def status_class(self):
        return self.TONE.get(self.status, "grey")

    @property
    def estimated_cost(self):
        """What this costs if it pays out in full - the number a manager judges."""
        if self.reward_type == self.Reward.POINTS:
            return Decimal("0.00")
        return self.reward_amount * self.target_units

    @property
    def cost_per_unit_label(self):
        if self.reward_type == self.Reward.POINTS:
            return f"{self.reward_amount:.0f} pts/unit"
        return f"${self.reward_amount:,.2f}/unit"

    @property
    def is_editable(self):
        return self.status in (self.State.DRAFT, self.State.REJECTED)

    @property
    def is_decidable(self):
        return self.status == self.State.SUBMITTED

    def can_be_decided_by(self, agent):
        """Only a manager who owns the plan's team may approve or reject it."""
        return (
            agent is not None
            and agent.is_manager
            and self.team.manager_id == agent.pk
            and self.is_decidable
        )

    @property
    def search_blob(self):
        return " ".join([
            self.name, self.product, self.category,
            self.team.name, self.get_status_display(),
        ]).lower()


# ==========================================================================
# Spend management (manager dashboard)
# ==========================================================================
class Budget(models.Model):
    """
    The incentive budget a manager is working to.

    Editable from the dashboard: change it and utilisation, the trend ceiling
    and the "within plan" verdict all recompute from spend.
    """

    region = models.CharField(max_length=60)
    period = models.CharField(max_length=40, default="August 2026")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    set_by = models.ForeignKey(
        AgentProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="budgets_set",
    )
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["region"]
        unique_together = [("region", "period")]

    def __str__(self):
        return f"{self.region} {self.period}: {self.amount}"


class Channel(models.Model):
    """
    A sales channel in the region - retail, inbound, outbound and so on.

    Channel-level figures come from the wider business, not from this portal's
    23 seeded people, so they live here rather than being derived.
    """

    region = models.CharField(max_length=60)
    name = models.CharField(max_length=60)
    icon = models.CharField(max_length=8, default="\U0001F4CA")
    agents = models.PositiveIntegerField(default=0)
    spend = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    attainment = models.PositiveSmallIntegerField(default=0)
    avg_payout = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    change_pct = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "-spend"]

    def __str__(self):
        return f"{self.name} ({self.region})"

    @property
    def direction(self):
        return "up" if self.change_pct > 0 else ("down" if self.change_pct < 0 else "flat")

    @property
    def bar_class(self):
        if self.attainment >= 100:
            return "green"
        return "amber" if self.attainment < 70 else ""


class PayoutException(models.Model):
    """
    A payout the system has flagged for a human to look at.

    Real workflow: a manager clears it or escalates it, with a note, and the
    decision is recorded. Nothing is paid while an exception is pending.
    """

    class Kind(models.TextChoices):
        HIGH_PAYOUT = "High payout", "Payout well above channel average"
        LOW_VOLUME = "Low volume", "Volume well below channel norm"
        DUPLICATE = "Duplicate", "Possible duplicate credit"
        CAP = "Near cap", "Approaching the payout cap"

    class State(models.TextChoices):
        PENDING = "Pending", "Pending review"
        ESCALATED = "Escalated", "Escalated"
        CLEARED = "Cleared", "Cleared for payment"

    TONE = {State.PENDING: "amber", State.ESCALATED: "red", State.CLEARED: "green"}

    agent = models.ForeignKey(
        AgentProfile, on_delete=models.CASCADE, related_name="exceptions"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    detail = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    flagged_on = models.DateField(null=True, blank=True)

    decided_by = models.ForeignKey(
        AgentProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="exceptions_decided",
    )
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["status", "-amount"]

    def __str__(self):
        return f"{self.kind} - {self.agent.full_name} ({self.amount})"

    @property
    def status_class(self):
        return self.TONE.get(self.status, "grey")

    @property
    def is_pending(self):
        return self.status == self.State.PENDING

    def can_be_decided_by(self, approver):
        """Only the manager who owns this agent's team may decide."""
        team = self.agent.team
        return bool(
            approver is not None
            and approver.is_manager
            and team is not None
            and team.manager_id == approver.pk
            and self.is_pending
        )


class PeriodClose(models.Model):
    """
    Closing a period: freeze the numbers, clear every exception, then hand
    the total to payroll.

    The rules are the point. A close cannot be calculated while an exception
    is still open, cannot be approved before it has been calculated, and
    cannot be touched at all once payroll has it. Each step records who did
    it and when, so the figure payroll receives is traceable to a person.
    """

    class State(models.TextChoices):
        OPEN = "Open", "Open - not yet calculated"
        CALCULATED = "Calculated", "Calculated - awaiting approval"
        APPROVED = "Approved", "Approved for payroll"

    TONE = {State.OPEN: "amber", State.CALCULATED: "blue", State.APPROVED: "green"}

    region = models.CharField(max_length=60)
    period = models.CharField(max_length=30)
    status = models.CharField(max_length=12, choices=State.choices, default=State.OPEN)

    # Frozen at calculation time, so later edits cannot change what payroll saw.
    agent_payouts = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    plan_commitments = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    approved_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    headcount = models.PositiveIntegerField(default=0)

    calculated_by = models.ForeignKey(
        AgentProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="closes_calculated")
    calculated_on = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        AgentProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="closes_approved")
    approved_on = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        unique_together = [("region", "period")]
        ordering = ["-period"]

    def __str__(self):
        return f"{self.region} {self.period} ({self.status})"

    @property
    def status_class(self):
        return self.TONE.get(self.status, "")

    @property
    def total(self):
        return self.agent_payouts + self.plan_commitments + self.approved_sales

    @property
    def is_locked(self):
        """Payroll has it; nothing may change."""
        return self.status == self.State.APPROVED

    @property
    def can_calculate(self):
        return self.status in (self.State.OPEN, self.State.CALCULATED)

    @property
    def can_approve(self):
        return self.status == self.State.CALCULATED

    def blocking_exceptions(self):
        """A period cannot close over an unresolved payout exception."""
        from .models import PayoutException
        return PayoutException.objects.filter(
            agent__team__region=self.region,
            status=PayoutException.State.PENDING,
        )


class Setting(models.Model):
    """
    Per-region thresholds and notification choices.

    Stored per region rather than globally: a coaching threshold that suits
    a mature Southwest team is not automatically right for the Northeast.
    Other pages read these, so changing one here changes what they show.
    """

    region = models.CharField(max_length=60, unique=True)

    coaching_threshold = models.PositiveSmallIntegerField(
        default=70, help_text="Attainment below this flags an agent for coaching")
    exception_threshold = models.DecimalField(
        max_digits=9, decimal_places=2, default=3000,
        help_text="A payout above this is held for review")
    close_reminder_days = models.PositiveSmallIntegerField(
        default=3, help_text="Days before period end to raise the close reminder")

    notify_on_dispute = models.BooleanField(default=True)
    notify_on_plan = models.BooleanField(default=True)
    notify_on_close = models.BooleanField(default=True)

    updated_by = models.ForeignKey(
        AgentProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="settings_updated")
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Settings for {self.region}"
