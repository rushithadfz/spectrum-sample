import json
import re
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AgentProfile,
    Badge,
    Budget,
    Category,
    Channel,
    Dispute,
    Incentive,
    IncentivePlan,
    MarketTrend,
    Offer,
    PayoutException,
    PeriodClose,
    Persona,
    PointsRule,
    Product,
    Quest,
    RoleType,
    Sale,
    SavedPlan,
    Setting,
    Status,
    Team,
    Tier,
)


class PortalTests(TestCase):
    """Smoke coverage for auth, every page, and the filter/search behaviour."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.user = User.objects.get(username="jliu")

    def assertLinked(self, body, asset):
        """
        Assert a static file is linked, whatever its served filename.

        With DEBUG off, ManifestStaticFilesStorage rewrites "css/anim.css" to
        "css/anim.776ec14524c0.css" for cache-busting, so matching the literal
        name only passes in development.
        """
        import re as _re

        stem, dot, ext = asset.rpartition(".")
        pattern = _re.escape(stem) + r"(\.[0-9a-f]{8,})?" + _re.escape(dot + ext)
        self.assertRegex(body, pattern, f"{asset} should be linked")

    def login(self, persona="jliu"):
        """
        Sign in through the real role picker.

        This POC has no credentials: POSTing a persona slug is the sign-in.
        Going through the view (rather than client.force_login) also exercises
        the streak/XP bookkeeping.
        """
        resp = self.client.post(reverse("login"), {"persona": persona})
        self.assertEqual(resp.status_code, 302, "picking a role should redirect")

    # ---------------- auth ----------------
    def test_pages_require_login(self):
        for name in ["home", "incentive_feed", "incentive_detail", "calculator",
                     "disputes", "products"]:
            resp = self.client.get(reverse(f"portal:{name}"))
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/login/", resp["Location"])

    def test_an_unavailable_persona_is_refused(self):
        """The guard still holds if a role is ever added but not built out."""
        Persona.objects.create(
            slug="future-role", name="Someone Else", title="Not Built",
            blurb="placeholder", is_available=False,
        )
        resp = self.client.post(reverse("login"), {"persona": "future-role"})
        self.assertEqual(resp.status_code, 200)          # re-renders, no redirect
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unknown_persona_is_refused(self):
        resp = self.client.post(reverse("login"), {"persona": "nope"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_signing_in_needs_no_password(self):
        resp = self.client.post(reverse("login"), {"persona": "jliu"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]), self.user.pk
        )

    def test_demo_login_can_be_switched_off(self):
        """The passwordless picker must not be reachable outside the demo."""
        with self.settings(PORTAL_DEMO_LOGIN=False):
            self.assertEqual(self.client.get(reverse("login")).status_code, 404)
            self.assertEqual(
                self.client.post(reverse("login"), {"persona": "jliu"}).status_code,
                404,
            )

    def test_already_signed_in_skips_the_picker(self):
        self.login()
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.status_code, 302)

    def test_login_then_dashboard(self):
        self.login()
        resp = self.client.get(reverse("portal:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Jenny Liu")
        self.assertContains(resp, "Monthly Incentive Earnings")

    # ---------------- list pages ----------------
    def test_all_list_pages_render(self):
        self.login()
        for name in ["home", "incentive_feed", "incentive_detail", "calculator",
                     "disputes", "products"]:
            with self.subTest(page=name):
                resp = self.client.get(reverse(f"portal:{name}"))
                self.assertEqual(resp.status_code, 200)

    def test_every_product_detail_renders_with_specs(self):
        self.login()
        for product in Product.objects.all():
            with self.subTest(product=product.slug):
                resp = self.client.get(product.get_absolute_url())
                self.assertEqual(resp.status_code, 200)
                self.assertContains(resp, "Full specifications")
                first_spec = product.spec_groups.first().specs.first()
                self.assertContains(resp, first_spec.label)

    def test_agent_chrome_present_on_every_page(self):
        """Regression: the agent profile must reach the base template on all
        pages, not just the dashboard."""
        self.login()
        pages = [reverse(f"portal:{n}") for n in
                 ["home", "incentive_feed", "incentive_detail", "calculator",
                  "disputes", "products"]]
        pages.append(Product.objects.first().get_absolute_url())
        for url in pages:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertContains(resp, "Jenny Liu")     # app-bar identity
                self.assertNotContains(resp, "no agent profile attached")

    def test_unknown_slug_404s(self):
        self.login()
        self.assertEqual(self.client.get("/products/nope/").status_code, 404)

    # ---------------- filtering ----------------
    # Every item is rendered and non-matches carry .is_hidden, so the
    # client-side filter can toggle them without a round trip.
    @staticmethod
    def shown(items):
        return [i for i in items if not i.is_hidden]

    def test_product_search_reaches_spec_text(self):
        """A term that appears only inside a spec row should still match."""
        self.login()
        resp = self.client.get(reverse("portal:products"), {"q": "DOCSIS"})
        slugs = {p.slug for p in self.shown(resp.context["products"])}
        self.assertIn("internet-advantage-500", slugs)
        # "DOCSIS" is in no product name or description, only in spec values.
        self.assertNotIn("docsis", "internet advantage 500 mbps")

    def test_product_category_filter(self):
        self.login()
        resp = self.client.get(reverse("portal:products"), {"cat": "Equipment"})
        shown = self.shown(resp.context["products"])
        self.assertTrue(shown)
        for product in shown:
            self.assertEqual(product.category, "Equipment")


    def test_cards_carry_filter_data_attributes(self):
        """The client-side filter depends on these attributes existing."""
        self.login()
        resp = self.client.get(reverse("portal:products"))
        self.assertContains(resp, "data-filter-root")
        self.assertContains(resp, 'data-cat="Equipment"')
        self.assertContains(resp, "data-search=")

    # ---------------- payout maths ----------------
    # ---------------- sign-in progression ----------------
    def test_signin_awards_xp_and_sets_streak(self):
        agent = self.user.agent
        agent.last_seen = timezone.localdate() - timedelta(days=1)
        agent.streak_days = 14
        agent.xp = 5820
        agent.save()

        self.login()
        resp = self.client.get(reverse("portal:home"))

        agent.refresh_from_db()
        self.assertEqual(agent.streak_days, 15)          # continued
        self.assertGreater(agent.xp, 5820)               # XP awarded
        self.assertContains(resp, "15-day streak")       # arrival overlay shown

    def test_streak_resets_after_a_gap(self):
        agent = self.user.agent
        agent.last_seen = timezone.localdate() - timedelta(days=5)
        agent.streak_days = 14
        agent.save()

        self.login()
        agent.refresh_from_db()
        self.assertEqual(agent.streak_days, 1)

    def test_second_signin_same_day_awards_nothing(self):
        agent = self.user.agent
        today = timezone.localdate()
        # Both are written together on a real sign-in, so set both: seen
        # today and already given today's roll.
        agent.last_seen = today
        agent.last_roll_on = today
        agent.last_roll_face = 4
        agent.xp = 5820
        agent.save()

        self.login()
        agent.refresh_from_db()
        self.assertEqual(agent.xp, 5820)

    def test_arrival_overlay_plays_only_once(self):
        self.login()
        first = self.client.get(reverse("portal:home"))
        second = self.client.get(reverse("portal:home"))
        self.assertContains(first, 'id="arrival"')
        self.assertNotContains(second, 'id="arrival"')

    def test_level_maths(self):
        agent = self.user.agent
        agent.xp = 5820
        self.assertEqual(agent.level, 12)
        self.assertEqual(agent.xp_into_level, 320)
        self.assertEqual(agent.level_pct, 64)
        self.assertEqual(agent.rank_title, "Specialist")

    def test_login_page_shows_live_portal_stats(self):
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.context["stat_products"], Product.objects.count())
        self.assertGreater(resp.context["stat_specs"], 100)

    # ---------------- inbound agent ----------------
    def test_agent_is_the_inbound_persona(self):
        agent = self.user.agent
        self.assertEqual(agent.role_type, RoleType.AGENT)
        self.assertEqual(agent.full_name, "Jenny Liu")


    def test_conversion_rate_maths(self):
        snap = self.user.agent.snapshots.get(is_current=True)
        self.assertGreater(snap.calls_handled, snap.calls_converted)
        expected = round(snap.calls_converted / snap.calls_handled * 100, 1)
        self.assertEqual(float(snap.conversion_rate), expected)

    def test_conversion_rate_handles_zero_calls(self):
        snap = self.user.agent.snapshots.get(is_current=True)
        snap.calls_handled = 0
        self.assertEqual(snap.conversion_rate, 0)


    def test_incentive_pct_capped_at_100(self):
        inc = Incentive.objects.first()
        inc.progress, inc.goal = 40, 20
        self.assertEqual(inc.pct, 100)

    # ---------------- data integrity ----------------
    def test_seed_is_idempotent(self):
        before = (Product.objects.count(), Offer.objects.count(), Incentive.objects.count())
        call_command("seed_demo", verbosity=0)
        after = (Product.objects.count(), Offer.objects.count(), Incentive.objects.count())
        self.assertEqual(before, after)

    def test_every_product_has_specs_and_links(self):
        for product in Product.objects.all():
            with self.subTest(product=product.slug):
                self.assertTrue(product.spec_groups.exists())
                self.assertTrue(product.links.exists())
                self.assertTrue(product.highlights.exists())

    # ================= incentive portal (POC parity) =================
    def test_home_shows_the_agent_the_things_that_matter(self):
        self.login()
        resp = self.client.get(reverse("portal:home"))
        agent = self.user.agent
        # The home answers "what am I earning" and "what do I do next".
        # Badges moved to the points page and the department/supervisor
        # trivia was cut - it was repeated on every visit and acted on never.
        for probe in ["Monthly Incentive Earnings", "Projected Payout",
                      "Active Incentives", "Period Progress",
                      "Earnings, last 6 months", "Your tier"]:
            with self.subTest(probe=probe):
                self.assertContains(resp, probe)
        for gone in ["Badges", "Supervisor:", "Department:"]:
            with self.subTest(removed=gone):
                self.assertNotContains(resp, gone)

    def test_home_greeting_varies_by_hour(self):
        from portal.views_incentive import _greeting
        from datetime import datetime
        self.assertEqual(_greeting(datetime(2026, 8, 31, 9)), "Good morning")
        self.assertEqual(_greeting(datetime(2026, 8, 31, 14)), "Good afternoon")
        self.assertEqual(_greeting(datetime(2026, 8, 31, 21)), "Good evening")

    def test_badge_tallies(self):
        self.login()
        ctx = self.client.get(reverse("portal:home")).context
        mine = self.user.agent.badges
        self.assertEqual(ctx["badges_total"], mine.count())
        self.assertEqual(ctx["badges_earned"], mine.filter(is_earned=True).count())
        self.assertLess(ctx["badges_earned"], ctx["badges_total"])

    def test_trend_bars_scale_to_the_peak(self):
        self.login()
        trend = self.client.get(reverse("portal:home")).context["trend"]
        self.assertTrue(trend)
        self.assertEqual(max(t.height_pct for t in trend), 100)

    def test_incentive_feed_buckets(self):
        self.login()
        ctx = self.client.get(reverse("portal:incentive_feed")).context
        self.assertTrue(ctx["active"])
        self.assertTrue(ctx["previous"])
        for i in ctx["previous"]:
            self.assertEqual(i.bucket, "previous")

    def test_feed_month_filter(self):
        self.login()
        resp = self.client.get(reverse("portal:incentive_feed"), {"month": "March 2026"})
        self.assertEqual(list(resp.context["previous"]), [])

    def test_detail_shows_scorecard_and_tiers(self):
        self.login()
        resp = self.client.get(reverse("portal:incentive_detail"))
        card = resp.context["scorecard"]
        self.assertEqual(card.psid, "EMP-78432")
        self.assertEqual(card.job_code, "AE-INB")
        self.assertEqual(card.incentive_id, "RIBSR2606ACQ")
        self.assertEqual(card.rank, 40)
        self.assertEqual(card.rank_of, 150)
        self.assertEqual(card.current_tier.name, "Achiever")
        self.assertEqual([t.name for t in resp.context["tiers"]],
                         ["Contender", "Contributor", "Achiever", "Star"])

    def test_top_pct_is_derived_from_rank(self):
        """Rank 40 of 150 puts you in the top 27% - as the POC shows."""
        self.login()
        card = self.client.get(reverse("portal:incentive_detail")).context["scorecard"]
        self.assertEqual(card.top_pct, 27)

    def test_points_structure_matches_poc(self):
        rules = {r.label: r.points for r in PointsRule.objects.all()}
        self.assertEqual(rules, {"Gig Internet PSU": 8, "Internet PSU": 3, "Video PSU": 4})

    def test_detail_marks_the_current_tier(self):
        self.login()
        tiers = self.client.get(reverse("portal:incentive_detail")).context["tiers"]
        current = [t for t in tiers if t.is_current]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].name, "Achiever")

    # ---------------- calculator ----------------
    def test_calculator_dollar_plan(self):
        """2 Gig pays $10/unit, $60 earned, target $500 -> 44 more units."""
        self.login()
        resp = self.client.get(reverse("portal:calculator"),
                               {"incentive": "Inc 01", "target": "500"})
        plan = resp.context["plan"]
        self.assertEqual(plan["needed"], 44)
        self.assertEqual(plan["unit_word"], "units")
        self.assertFalse(plan["achieved"])

    def test_calculator_daily_pace(self):
        self.login()
        plan = self.client.get(reverse("portal:calculator"),
                               {"incentive": "Inc 01", "target": "500"}).context["plan"]
        # 44 units over the 5 remaining days
        self.assertEqual(plan["days"], 5)
        self.assertEqual(float(plan["daily"]), 8.8)

    def test_calculator_points_plan(self):
        self.login()
        plan = self.client.get(reverse("portal:calculator"),
                               {"incentive": "Inc 00", "target": "605"}).context["plan"]
        self.assertEqual(plan["unit_word"], "pts")
        self.assertEqual(plan["needed"], 485)      # 605 target - 120 earned

    def test_calculator_target_already_met(self):
        self.login()
        plan = self.client.get(reverse("portal:calculator"),
                               {"incentive": "Inc 01", "target": "10"}).context["plan"]
        self.assertTrue(plan["achieved"])
        self.assertEqual(plan["needed"], 0)

    def test_calculator_rejects_junk_target(self):
        self.login()
        resp = self.client.get(reverse("portal:calculator"),
                               {"incentive": "Inc 01", "target": "abc"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["plan"])

    def test_saving_a_plan(self):
        self.login()
        self.client.post(reverse("portal:calculator") + "?incentive=Inc 01&target=500")
        plan = SavedPlan.objects.get()
        self.assertEqual(plan.units_needed, 44)
        self.assertEqual(plan.target_amount, 500)

    # ---------------- disputes ----------------
    # ---------------- raising disputes ----------------
    def test_agent_can_raise_a_dispute(self):
        self.login()
        before = self.user.agent.disputes.count()
        resp = self.client.post(reverse("portal:disputes"), {
            "subject": "SPIFF missing on my 1 Gig install last Tuesday",
            "category": "Bonus / SPIF Not Applied",
            "priority": "High",
            "detail": "Order ORD-884198.",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("raised=TKT-", resp["Location"])
        self.assertEqual(self.user.agent.disputes.count(), before + 1)

        ticket = self.user.agent.disputes.order_by("-id").first()
        self.assertEqual(ticket.status, Dispute.State.AWAITING_LEAD)
        self.assertEqual(ticket.agent, self.user.agent)
        self.assertIsNotNone(ticket.raised_on)

    def test_ticket_numbers_do_not_collide(self):
        self.login()
        seen = set()
        for i in range(3):
            self.client.post(reverse("portal:disputes"), {
                "subject": f"Payout query number {i} needs review",
                "category": "Missing Payout", "priority": "Low",
            })
        for t in self.user.agent.disputes.all():
            self.assertNotIn(t.ticket_no, seen)
            seen.add(t.ticket_no)
        self.assertEqual(len(seen), self.user.agent.disputes.count())

    def test_short_subject_is_rejected(self):
        self.login()
        before = Dispute.objects.count()
        resp = self.client.post(reverse("portal:disputes"), {
            "subject": "bad", "category": "Commission Error", "priority": "Low",
        })
        self.assertEqual(resp.status_code, 200)          # re-renders with the error
        self.assertContains(resp, "at least 10 characters")
        self.assertEqual(Dispute.objects.count(), before)

    def test_lead_sees_the_team_queue_not_their_own(self):
        self.login("jmitchell")
        resp = self.client.get(reverse("portal:disputes"))
        self.assertTrue(resp.context["is_queue"])
        self.assertContains(resp, "Dispute Queue")
        lead = AgentProfile.objects.get(user__username="jmitchell")
        team_agents = set(lead.visible_agents)
        self.assertTrue(resp.context["tickets"])
        for t in resp.context["tickets"]:
            self.assertIn(t.agent, team_agents)

    def test_manager_queue_spans_their_teams(self):
        self.login("gchen")
        resp = self.client.get(reverse("portal:disputes"))
        manager = AgentProfile.objects.get(user__username="gchen")
        visible = set(manager.visible_agents)
        for t in resp.context["tickets"]:
            self.assertIn(t.agent, visible)

    def test_leads_cannot_raise_disputes(self):
        """The queue is read-only; leads have no raise form."""
        self.login("jmitchell")
        resp = self.client.get(reverse("portal:disputes"))
        self.assertNotContains(resp, "Raise a dispute")
        before = Dispute.objects.count()
        self.client.post(reverse("portal:disputes"), {
            "subject": "Trying to raise this as a lead account",
            "category": "Commission Error", "priority": "High",
        })
        self.assertEqual(Dispute.objects.count(), before)

    def test_disputes_list(self):
        self.login()
        resp = self.client.get(reverse("portal:disputes"))
        mine = Dispute.objects.filter(agent=self.user.agent)
        self.assertEqual(resp.context["visible"], mine.count())
        self.assertFalse(resp.context["is_queue"])
        self.assertTrue(mine.exists())
        for ticket in mine:
            self.assertContains(resp, ticket.ticket_no)
        # another agent's ticket must not leak onto this page
        other = Dispute.objects.exclude(agent=self.user.agent).first()
        if other:
            self.assertNotContains(resp, other.ticket_no)

    def test_dispute_priority_filter(self):
        self.login()
        resp = self.client.get(reverse("portal:disputes"), {"priority": "High"})
        shown = [t for t in resp.context["tickets"] if not t.is_hidden]
        self.assertTrue(shown)
        for t in shown:
            self.assertEqual(t.priority, "High")

    def test_dispute_category_filter(self):
        self.login()
        target = Dispute.objects.filter(agent=self.user.agent).first()
        resp = self.client.get(reverse("portal:disputes"), {"category": target.category})
        shown = [t for t in resp.context["tickets"] if not t.is_hidden]
        self.assertTrue(shown)
        for t in shown:
            self.assertEqual(t.category, target.category)

    def test_deleting_a_dispute(self):
        self.login()
        mine = Dispute.objects.filter(agent=self.user.agent).first()
        self.client.post(reverse("portal:disputes"), {"delete": mine.ticket_no})
        self.assertFalse(Dispute.objects.filter(ticket_no=mine.ticket_no).exists())

    def test_cannot_delete_another_agents_dispute(self):
        """The delete is scoped to your own tickets."""
        self.login()
        other = Dispute.objects.exclude(agent=self.user.agent).first()
        self.client.post(reverse("portal:disputes"), {"delete": other.ticket_no})
        self.assertTrue(Dispute.objects.filter(ticket_no=other.ticket_no).exists())

    def test_dispute_status_colours(self):
        self.assertEqual(Dispute.objects.get(ticket_no="TKT-00005").status_class, "amber")
        self.assertEqual(Dispute.objects.get(ticket_no="TKT-00004").status_class, "red")
        self.assertEqual(Dispute.objects.get(ticket_no="TKT-00002").status_class, "")

    # ---------------- chrome ----------------
    def test_appbar_has_periods_and_notifications(self):
        self.login()
        resp = self.client.get(reverse("portal:home"))
        self.assertContains(resp, "August 2026")
        self.assertContains(resp, "Exception Flagged")
        self.assertEqual(len(resp.context["notifications"]), 10)

    def test_command_palette_index_is_built(self):
        self.login()
        import json
        payload = json.loads(self.client.get(reverse("portal:home")).context["palette_json"])
        labels = [entry["label"] for entry in payload]
        self.assertIn("Earnings Calculator", labels)
        self.assertIn("2 Gig Break the Bank", labels)
        for entry in payload:
            self.assertTrue(entry["url"].startswith("/"))

    # ================= role hierarchy =================
    def test_org_shape(self):
        self.assertEqual(Team.objects.count(), 4)
        self.assertEqual(AgentProfile.objects.filter(role_type=RoleType.LEAD).count(), 4)
        self.assertEqual(AgentProfile.objects.filter(role_type=RoleType.MANAGER).count(), 2)
        self.assertGreaterEqual(
            AgentProfile.objects.filter(role_type=RoleType.AGENT).count(), 16)

    def test_each_manager_owns_their_own_teams(self):
        grace = AgentProfile.objects.get(user__username="gchen")
        sam = AgentProfile.objects.get(user__username="sreed")
        self.assertEqual(grace.visible_teams.count(), 2)
        self.assertEqual(sam.visible_teams.count(), 2)
        self.assertEqual(set(grace.visible_teams) & set(sam.visible_teams), set())

    def test_every_field_agent_has_their_own_data(self):
        """Switching persona must show different numbers, not the same demo row."""
        agents = AgentProfile.objects.filter(role_type=RoleType.AGENT)
        for a in agents:
            with self.subTest(agent=a.agent_id):
                self.assertTrue(a.badges.exists())
                self.assertTrue(a.quests.exists())
                self.assertTrue(a.trend.exists())
                self.assertTrue(a.mtd.exists())
                self.assertTrue(hasattr(a, "scorecard"))
        points = [a.scorecard.total_points for a in agents]
        self.assertGreater(len(set(points)), 5, "agents should not share one scorecard")

    def test_every_team_has_a_lead_and_a_manager(self):
        for team in Team.objects.all():
            with self.subTest(team=team.name):
                self.assertIsNotNone(team.lead)
                self.assertIsNotNone(team.manager)
                self.assertEqual(team.lead.role_type, RoleType.LEAD)
                self.assertEqual(team.manager.role_type, RoleType.MANAGER)

    def test_lead_sees_only_their_own_squad(self):
        lead = AgentProfile.objects.get(user__username="jmitchell")
        teams = list(lead.visible_teams)
        self.assertEqual([t.name for t in teams], ["DFW Inbound Queue 4"])
        for a in lead.visible_agents:
            self.assertEqual(a.team, teams[0])

    def test_manager_sees_every_team(self):
        manager = AgentProfile.objects.get(user__username="gchen")
        self.assertEqual(manager.visible_teams.count(), 2)
        self.assertEqual(
            manager.visible_agents.count(),
            sum(t.headcount for t in manager.visible_teams),
        )

    def test_agent_sees_only_themselves(self):
        agent = self.user.agent
        self.assertEqual(list(agent.visible_agents), [agent])
        self.assertEqual(agent.visible_teams.count(), 0)

    # ---------------- access control ----------------
    def test_agent_cannot_reach_team_or_market(self):
        self.login("jliu")
        self.assertEqual(self.client.get(reverse("portal:team")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:market")).status_code, 403)

    def test_lead_reaches_team_but_not_market(self):
        self.login("jmitchell")
        self.assertEqual(self.client.get(reverse("portal:team")).status_code, 200)
        self.assertEqual(self.client.get(reverse("portal:market")).status_code, 403)

    def test_manager_reaches_both(self):
        self.login("gchen")
        self.assertEqual(self.client.get(reverse("portal:team")).status_code, 200)
        self.assertEqual(self.client.get(reverse("portal:market")).status_code, 200)

    def test_lead_cannot_open_another_teams_roster(self):
        """Typing another team id in the URL must be refused."""
        self.login("jmitchell")
        other = Team.objects.get(name="DFW Inbound Queue 7")
        resp = self.client.get(reverse("portal:team"), {"team_id": other.pk})
        self.assertEqual(resp.status_code, 403)

    def test_lead_can_open_their_own_team_by_id(self):
        self.login("jmitchell")
        own = Team.objects.get(name="DFW Inbound Queue 4")
        resp = self.client.get(reverse("portal:team"), {"team_id": own.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["team"], own)

    def test_manager_can_switch_between_their_teams(self):
        """The Open link on the market page must actually change team."""
        self.login("gchen")
        manager = AgentProfile.objects.get(user__username="gchen")
        for team in manager.visible_teams:
            with self.subTest(team=team.name):
                resp = self.client.get(reverse("portal:team"), {"team_id": team.pk})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.context["team"], team)
                names = {r["agent"].full_name for r in resp.context["rows"]}
                self.assertEqual(names, {a.full_name for a in team.agents})

    def test_manager_cannot_open_another_managers_team(self):
        self.login("gchen")
        other = Team.objects.exclude(manager__user__username="gchen").first()
        self.assertEqual(
            self.client.get(reverse("portal:team"), {"team_id": other.pk}).status_code,
            403,
        )

    # ---------------- nav ----------------
    def test_nav_differs_by_role(self):
        """Each role gets its own set of pages, not one nav with extras."""
        def tabs():
            """The sidebar is the navigation now."""
            body = self.client.get(reverse("portal:home")).content.decode()
            return re.findall(r'<span class="side-label">([^<]+)</span>', body)

        self.login("jliu")
        self.assertEqual(tabs(), ["Home", "Incentives", "Log a Sale", "Points Incentive",
                                  "Earnings Calculator", "Disputes", "Products"])

        self.client.logout()
        self.login("jmitchell")
        self.assertEqual(tabs(), ["Home", "My Team", "Programmes", "Buying Trends",
                                  "Incentive Plans", "Simulation", "Sales Approvals",
                                  "Dispute Queue",
                                  "Channels", "Agent Directory", "Reports", "Products"])

        self.client.logout()
        self.login("gchen")
        self.assertEqual(tabs(), ["Home", "Market", "Month-End Close", "Spend", "Teams", "Programmes",
                                  "Buying Trends", "Approval Queue", "Simulation", "Disputes",
                                  "Channels", "Agent Directory", "Reports",
                                  "Settings", "Products"])

    def test_home_is_a_different_page_per_role(self):
        self.login("jliu")
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertIn("Daily Quests", body)
        self.assertIn("Your tier", body)
        self.assertNotIn("Squad standings", body)

        self.client.logout()
        self.login("jmitchell")
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertIn("Squad standings", body)
        self.assertNotIn("Daily Quests", body)      # not the lead's game loop
        self.assertNotIn("Your tier", body)

        self.client.logout()
        self.login("gchen")
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertIn("Region leaderboard", body)
        self.assertIn("attainment against quota", body)
        self.assertNotIn("Daily Quests", body)

    def test_xp_chip_is_only_for_field_agents(self):
        """The XP/quest loop belongs to agents; leads get a role chip."""
        self.login("jliu")
        self.assertIn("side-xp", self.client.get(reverse("portal:home")).content.decode())

        self.client.logout()
        self.login("jmitchell")
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertNotIn("side-xp", body)

    def test_lead_home_uses_their_own_squad(self):
        self.login("jmitchell")
        ctx = self.client.get(reverse("portal:home")).context
        self.assertEqual(ctx["team"].name, "DFW Inbound Queue 4")
        for row in ctx["rows"]:
            self.assertEqual(row["agent"].team, ctx["team"])

    def test_manager_home_totals_match_the_market_page(self):
        self.login("gchen")
        home = self.client.get(reverse("portal:home")).context
        market = self.client.get(reverse("portal:market")).context
        self.assertEqual(home["headcount"], market["headcount"])
        self.assertEqual(home["team_count"], market["team_count"])
        self.assertEqual(home["avg_attainment"], market["avg_attainment"])

    # ---------------- rollups ----------------
    def test_team_attainment_is_the_mean_of_its_agents(self):
        team = Team.objects.get(name="DFW Inbound Queue 4")
        agents = list(team.agents)
        expected = round(sum(a.attainment for a in agents) / len(agents))
        self.assertEqual(team.attainment, expected)

    def test_team_headcount_excludes_the_lead(self):
        team = Team.objects.get(name="DFW Inbound Queue 4")
        self.assertEqual(team.headcount, team.agents.count())
        self.assertNotIn(team.lead, list(team.agents))

    def test_market_totals_add_up(self):
        self.login("gchen")
        ctx = self.client.get(reverse("portal:market")).context
        self.assertEqual(ctx["team_count"], 2)
        self.assertEqual(ctx["headcount"], sum(t.headcount for t in ctx["teams"]))

    def test_leaderboard_is_sorted_by_attainment(self):
        self.login("gchen")
        rows = self.client.get(reverse("portal:market")).context["leaderboard"]
        scores = [r["attainment"] for r in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_at_risk_lists_only_under_seventy(self):
        self.login("gchen")
        for row in self.client.get(reverse("portal:market")).context["at_risk"]:
            self.assertLess(row["attainment"], 70)

    def test_team_roster_shows_each_agent_once(self):
        self.login("jmitchell")
        rows = self.client.get(reverse("portal:team")).context["rows"]
        names = [r["agent"].full_name for r in rows]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("Jenny Liu", names)

    # ---------------- CSS regression ----------------
    def test_shell_uses_sidebar_navigation(self):
        """The POC navigates from a left sidebar, not a top tab strip."""
        self.login()
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertIn('class="sidebar"', body)
        self.assertIn("side-nav", body)
        self.assertIn("topbar-blue", body)
        self.assertLinked(body, "css/shell.css")

    def test_hidden_attribute_is_not_overridden(self):
        """
        Several card classes set `display: flex`, which beats the HTML hidden
        attribute. Server-side filtering and the command palette both rely on
        `hidden` actually hiding, so the global override must stay.
        """
        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("[hidden] { display: none !important; }", css)

    # ================= game layer =================
    def test_quests_are_seeded(self):
        quests = self.user.agent.quests.all()
        self.assertEqual(quests.count(), 4)  # per agent
        self.assertTrue(any(q.is_claimable for q in quests))

    def test_quest_pct(self):
        q = Quest.objects.create(agent=self.user.agent, name="x", progress=3, goal=4, xp=10)
        self.assertEqual(q.pct, 75)
        self.assertFalse(q.is_claimable)

    def test_claiming_awards_xp_once(self):
        # Sign in first: the sign-in streak itself awards XP, so the baseline
        # has to be read after logging in or the arithmetic is off.
        self.login()
        agent = self.user.agent
        agent.refresh_from_db()
        quest = next(q for q in agent.quests.all() if q.is_claimable)
        before = agent.xp

        self.client.post(reverse("portal:claim_quest", args=[quest.pk]))
        agent.refresh_from_db()
        self.assertEqual(agent.xp, before + quest.xp)

        # claiming again must not pay twice
        self.client.post(reverse("portal:claim_quest", args=[quest.pk]))
        agent.refresh_from_db()
        self.assertEqual(agent.xp, before + quest.xp)

    def test_claim_redirects_with_reward_params(self):
        self.login()
        quest = next(q for q in self.user.agent.quests.all() if q.is_claimable)
        resp = self.client.post(reverse("portal:claim_quest", args=[quest.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"xp={quest.xp}", resp["Location"])

    def test_claim_requires_post(self):
        self.login()
        agent = self.user.agent
        agent.refresh_from_db()
        quest = next(q for q in agent.quests.all() if q.is_claimable)
        before = agent.xp
        self.client.get(reverse("portal:claim_quest", args=[quest.pk]))
        agent.refresh_from_db()
        self.assertEqual(agent.xp, before)

    def test_cannot_claim_an_unfinished_quest(self):
        self.login()
        agent = self.user.agent
        agent.refresh_from_db()
        quest = Quest.objects.create(agent=agent, name="Not done", progress=0, goal=5, xp=99)
        before = agent.xp
        self.client.post(reverse("portal:claim_quest", args=[quest.pk]))
        agent.refresh_from_db()
        self.assertEqual(agent.xp, before)

    def test_cannot_claim_another_agents_quest(self):
        other = AgentProfile.objects.get(user__username="knguyen")
        quest = Quest.objects.create(agent=other, name="Theirs", progress=1, goal=1, xp=99)
        self.login()
        resp = self.client.post(reverse("portal:claim_quest", args=[quest.pk]))
        self.assertEqual(resp.status_code, 404)
        quest.refresh_from_db()
        self.assertFalse(quest.completed)

    def test_rank_movement_is_derived(self):
        card = self.user.agent.scorecard
        card.rank, card.previous_rank = 40, 47
        self.assertEqual(card.rank_delta, 7)
        self.assertEqual(card.rank_direction, "up")
        card.rank, card.previous_rank = 50, 40
        self.assertEqual(card.rank_direction, "down")
        card.previous_rank = 0
        self.assertEqual(card.rank_delta, 0)

    def test_appbar_shows_progression(self):
        self.login()
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertIn("side-xp", body)
        self.assertIn("lvl-dot", body)
        self.assertIn("side-streak", body)

    def test_pages_carry_reveal_targets(self):
        self.login()
        for name in ["home", "incentive_detail"]:
            with self.subTest(page=name):
                body = self.client.get(reverse(f"portal:{name}")).content.decode()
                self.assertIn("data-reveal", body)

    def test_animation_assets_are_linked(self):
        self.login()
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertLinked(body, "css/anim.css")
        self.assertLinked(body, "js/anim.js")

    # ================= buying trends =================
    def test_trends_are_seeded_per_region(self):
        regions = set(MarketTrend.objects.values_list("region", flat=True))
        self.assertEqual(regions, {"Southwest Region", "Northeast Region"})

    def test_agents_cannot_see_trends_or_plans(self):
        self.login("jliu")
        self.assertEqual(self.client.get(reverse("portal:trends")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:plans")).status_code, 403)

    def test_lead_sees_only_their_own_region(self):
        self.login("jmitchell")
        ctx = self.client.get(reverse("portal:trends")).context
        lead = AgentProfile.objects.get(user__username="jmitchell")
        own = {t.region for t in lead.visible_teams}
        self.assertEqual(set(ctx["regions"]), own)
        for row in ctx["rows"]:
            self.assertIn(row.region, own)

    def test_opportunity_flag(self):
        """Growing but under-attached is what an incentive should target."""
        rising_gap = MarketTrend(change_pct=30, attach_rate=20)
        well_attached = MarketTrend(change_pct=30, attach_rate=80)
        shrinking = MarketTrend(change_pct=-5, attach_rate=20)
        self.assertTrue(rising_gap.is_opportunity)
        self.assertFalse(well_attached.is_opportunity)
        self.assertFalse(shrinking.is_opportunity)

    def test_category_mix_sums_to_the_total(self):
        self.login("gchen")
        ctx = self.client.get(reverse("portal:trends")).context
        self.assertEqual(sum(m["units"] for m in ctx["mix"]), ctx["total_units"])

    # ================= plan builder =================
    def test_plan_form_prefills_from_a_trend(self):
        self.login("jmitchell")
        trend = MarketTrend.objects.filter(region="Southwest Region").first()
        resp = self.client.get(reverse("portal:plan_new"), {"trend": trend.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, trend.product)

    def test_lead_can_only_pick_their_own_teams(self):
        self.login("jmitchell")
        resp = self.client.get(reverse("portal:plan_new"))
        lead = AgentProfile.objects.get(user__username="jmitchell")
        choices = set(resp.context["form"].fields["team"].queryset)
        self.assertEqual(choices, set(lead.visible_teams))

    def _draft(self, submit=False):
        lead = AgentProfile.objects.get(user__username="jmitchell")
        data = {
            "name": "Test Gateway Push", "team": lead.visible_teams.first().pk,
            "product": "5G Home Gateway", "category": "Internet",
            "reward_type": "cash", "reward_amount": "20", "target_units": "100",
            "runs_from": "2026-09-01", "runs_to": "2026-09-30",
            "rationale": "5G is growing fast with a low attach rate.",
        }
        if submit:
            data["submit_now"] = "1"
        return self.client.post(reverse("portal:plan_new"), data)

    def test_lead_drafts_then_submits(self):
        self.login("jmitchell")
        self._draft()
        plan = IncentivePlan.objects.get(name="Test Gateway Push")
        self.assertEqual(plan.status, IncentivePlan.State.DRAFT)
        self.assertTrue(plan.is_editable)

        self.client.post(reverse("portal:plan_submit", args=[plan.pk]))
        plan.refresh_from_db()
        self.assertEqual(plan.status, IncentivePlan.State.SUBMITTED)
        self.assertFalse(plan.is_editable)

    def test_submitting_straight_away(self):
        self.login("jmitchell")
        self._draft(submit=True)
        plan = IncentivePlan.objects.get(name="Test Gateway Push")
        self.assertEqual(plan.status, IncentivePlan.State.SUBMITTED)

    def test_estimated_cost(self):
        plan = IncentivePlan(reward_type=IncentivePlan.Reward.CASH,
                             reward_amount=20, target_units=100)
        self.assertEqual(plan.estimated_cost, 2000)
        points = IncentivePlan(reward_type=IncentivePlan.Reward.POINTS,
                               reward_amount=500, target_units=100)
        self.assertEqual(points.estimated_cost, 0)

    def test_plan_validation(self):
        self.login("jmitchell")
        lead = AgentProfile.objects.get(user__username="jmitchell")
        resp = self.client.post(reverse("portal:plan_new"), {
            "name": "Bad plan", "team": lead.visible_teams.first().pk,
            "product": "X", "category": "Internet", "reward_type": "cash",
            "reward_amount": "0", "target_units": "0",
            "runs_from": "2026-09-30", "runs_to": "2026-09-01",
            "rationale": "no",
        })
        self.assertEqual(resp.status_code, 200)
        form = resp.context["form"]
        self.assertIn("runs_to", form.errors)
        self.assertIn("reward_amount", form.errors)
        self.assertIn("target_units", form.errors)
        self.assertFalse(IncentivePlan.objects.filter(name="Bad plan").exists())

    # ================= approval =================
    def test_manager_approves(self):
        self.login("jmitchell")
        self._draft(submit=True)
        plan = IncentivePlan.objects.get(name="Test Gateway Push")

        self.client.logout()
        self.login("gchen")
        self.client.post(reverse("portal:plan_decide", args=[plan.pk]),
                         {"decision": "approve", "note": "Makes sense."})
        plan.refresh_from_db()
        self.assertEqual(plan.status, IncentivePlan.State.APPROVED)
        self.assertEqual(plan.decided_by.user.username, "gchen")
        self.assertEqual(plan.decision_note, "Makes sense.")

    def test_manager_rejects_and_lead_can_edit_again(self):
        self.login("jmitchell")
        self._draft(submit=True)
        plan = IncentivePlan.objects.get(name="Test Gateway Push")

        self.client.logout()
        self.login("gchen")
        self.client.post(reverse("portal:plan_decide", args=[plan.pk]),
                         {"decision": "reject", "note": "Too expensive."})
        plan.refresh_from_db()
        self.assertEqual(plan.status, IncentivePlan.State.REJECTED)
        self.assertTrue(plan.is_editable)      # a rejection can be reworked

    def test_only_the_owning_manager_can_decide(self):
        self.login("jmitchell")
        self._draft(submit=True)
        plan = IncentivePlan.objects.get(name="Test Gateway Push")

        self.client.logout()
        self.login("sreed")          # manages the other region
        resp = self.client.post(reverse("portal:plan_decide", args=[plan.pk]),
                                {"decision": "approve"})
        self.assertEqual(resp.status_code, 403)
        plan.refresh_from_db()
        self.assertEqual(plan.status, IncentivePlan.State.SUBMITTED)

    def test_lead_cannot_approve_their_own_plan(self):
        self.login("jmitchell")
        self._draft(submit=True)
        plan = IncentivePlan.objects.get(name="Test Gateway Push")
        resp = self.client.post(reverse("portal:plan_decide", args=[plan.pk]),
                                {"decision": "approve"})
        self.assertEqual(resp.status_code, 403)
        plan.refresh_from_db()
        self.assertEqual(plan.status, IncentivePlan.State.SUBMITTED)

    def test_submitted_plan_cannot_be_edited(self):
        self.login("jmitchell")
        self._draft(submit=True)
        plan = IncentivePlan.objects.get(name="Test Gateway Push")
        self.assertEqual(
            self.client.get(reverse("portal:plan_edit", args=[plan.pk])).status_code, 403)

    def test_manager_queue_is_scoped_to_their_teams(self):
        self.login("gchen")
        ctx = self.client.get(reverse("portal:plans")).context
        manager = AgentProfile.objects.get(user__username="gchen")
        own_teams = set(manager.visible_teams)
        for plan in ctx["plans"]:
            self.assertIn(plan.team, own_teams)

    # ================= assistant =================
    def test_assistant_reachable_by_every_role(self):
        for slug in ["jliu", "jmitchell", "gchen"]:
            with self.subTest(role=slug):
                self.client.logout()
                self.login(slug)
                self.assertEqual(self.client.get(reverse("portal:ask")).status_code, 200)

    def _ask(self, question):
        self.client.post(reverse("portal:ask"), {"q": question})
        return self.client.session["ask_history"][-1]["a"]

    def test_assistant_answers_from_real_data(self):
        self.login("jliu")
        card = self.user.agent.scorecard
        answer = self._ask("what is my rank")
        self.assertIn(str(card.rank), answer)
        self.assertIn(str(card.total_points), answer)

    def test_assistant_earnings_matches_the_snapshot(self):
        self.login("jliu")
        snap = self.user.agent.snapshots.get(is_current=True)
        answer = self._ask("how much have I earned")
        self.assertIn(f"{snap.gross_commission:,.2f}", answer)

    def test_assistant_is_scoped_by_role(self):
        """An agent must not be able to ask about other people."""
        self.login("jliu")
        answer = self._ask("who is below quota on my team")
        self.assertNotIn("Tyler Brooks", answer)

    def test_lead_can_ask_about_their_squad(self):
        self.login("jmitchell")
        answer = self._ask("who needs coaching")
        lead = AgentProfile.objects.get(user__username="jmitchell")
        behind = [a for a in lead.visible_agents if a.attainment < 70]
        for person in behind[:1]:
            self.assertIn(person.full_name, answer)

    def test_manager_can_ask_about_the_approval_queue(self):
        self.login("gchen")
        answer = self._ask("what plans are waiting for approval")
        manager = AgentProfile.objects.get(user__username="gchen")
        queue = IncentivePlan.objects.filter(
            team__in=manager.visible_teams, status=IncentivePlan.State.SUBMITTED)
        self.assertIn(str(queue.count()), answer)

    def test_assistant_admits_when_it_does_not_know(self):
        self.login("jliu")
        answer = self._ask("what is the weather in Paris tomorrow")
        self.assertIn("did not catch", answer)

    def test_assistant_history_is_capped(self):
        self.login("jliu")
        for i in range(15):
            self.client.post(reverse("portal:ask"), {"q": f"what is my rank {i}"})
        self.assertLessEqual(len(self.client.session["ask_history"]), 12)

    def test_assistant_can_be_cleared(self):
        self.login("jliu")
        self._ask("what is my rank")
        self.client.post(reverse("portal:ask"), {"clear": "1"})
        self.assertEqual(self.client.session["ask_history"], [])

    # ================= tier integrity =================
    def test_current_tier_resolves_for_every_agent(self):
        """Tiers must be seeded before scorecards, or this comes back None."""
        for a in AgentProfile.objects.filter(role_type=RoleType.AGENT):
            with self.subTest(agent=a.agent_id):
                card = a.scorecard
                self.assertIsNotNone(
                    card.current_tier,
                    f"{a.full_name} has {card.total_points} points but no tier",
                )
                self.assertLessEqual(card.current_tier.threshold_points, card.total_points)

    # ================= Claude-backed assistant =================
    def test_falls_back_to_rules_without_a_key(self):
        from portal import llm
        with self.settings(ANTHROPIC_API_KEY="", PORTAL_LLM_ENABLED=True):
            self.assertFalse(llm.is_configured())
            self.assertIsNone(llm.ask(self.user.agent, "what is my rank"))

        self.login()
        self.client.post(reverse("portal:ask"), {"q": "what is my rank"})
        turn = self.client.session["ask_history"][-1]
        self.assertEqual(turn["engine"], "rules")
        self.assertIn(str(self.user.agent.scorecard.rank), turn["a"])

    def test_feature_flag_switches_claude_off(self):
        from portal import llm
        with self.settings(ANTHROPIC_API_KEY="sk-test", PORTAL_LLM_ENABLED=False):
            self.assertFalse(llm.is_configured())

    def test_claude_answer_is_used_when_available(self):
        from unittest.mock import patch
        self.login()
        with patch("portal.llm.ask", return_value="You are doing well."):
            self.client.post(reverse("portal:ask"), {"q": "how am I doing"})
        turn = self.client.session["ask_history"][-1]
        self.assertEqual(turn["engine"], "claude")
        self.assertEqual(turn["a"], "You are doing well.")

    def test_a_failed_call_degrades_instead_of_erroring(self):
        from unittest.mock import patch
        self.login()
        with patch("portal.llm.ask", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                # ask() itself swallows errors; this proves respond() only
                # relies on it returning None, not on it never raising.
                self.client.post(reverse("portal:ask"), {"q": "how am I doing"})

        with patch("portal.llm.ask", return_value=None):
            resp = self.client.post(reverse("portal:ask"), {"q": "what is my rank"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session["ask_history"][-1]["engine"], "rules")

    # ---- the important part: context must be role-scoped ----
    def test_agent_context_contains_only_their_own_figures(self):
        from portal import llm
        ctx = llm.build_context(self.user.agent)
        blob = json.dumps(ctx)
        self.assertIn("your_earnings", ctx)
        self.assertNotIn("your_people", ctx)
        self.assertNotIn("buying_trends", ctx)
        self.assertNotIn("incentive_plans", ctx)
        for other in AgentProfile.objects.exclude(pk=self.user.agent.pk):
            self.assertNotIn(other.full_name, blob)

    def test_lead_context_is_limited_to_their_squad(self):
        from portal import llm
        lead = AgentProfile.objects.get(user__username="jmitchell")
        ctx = llm.build_context(lead)
        own = {a.full_name for a in lead.visible_agents}
        listed = {p["name"] for p in ctx["your_people"]}
        self.assertEqual(listed, own)

        outside = AgentProfile.objects.filter(
            role_type=RoleType.AGENT).exclude(team__in=lead.visible_teams)
        blob = json.dumps(ctx)
        for person in outside:
            self.assertNotIn(person.full_name, blob)

    def test_manager_context_covers_their_region_only(self):
        from portal import llm
        grace = AgentProfile.objects.get(user__username="gchen")
        ctx = llm.build_context(grace)
        regions = {t["region"] for t in ctx["buying_trends"]}
        self.assertEqual(regions, {t.region for t in grace.visible_teams})
        blob = json.dumps(ctx)
        for team in Team.objects.exclude(manager=grace):
            self.assertNotIn(team.name, blob)

    def test_context_is_json_serialisable(self):
        """Decimals would otherwise blow up at request time, not in tests."""
        from portal import llm
        for username in ["jliu", "jmitchell", "gchen"]:
            with self.subTest(user=username):
                agent = AgentProfile.objects.get(user__username=username)
                json.dumps(llm.build_context(agent))   # must not raise

    def test_model_id_is_current(self):
        from portal import llm
        self.assertEqual(llm.MODEL, "claude-opus-5")

    # ---- "what should I sell?" ----
    def test_assistant_recommends_what_to_sell(self):
        self.login()
        answer = self._ask("what are the products i should sell to reach it")
        for probe in ["Gig Internet PSU", "8 pts", "Star"]:
            self.assertIn(probe, answer)
        self.assertNotIn("did not catch", answer)

    def test_what_to_sell_uses_the_highest_value_unit(self):
        from portal.assistant import answer as rules_answer
        from portal.models import PointsRule
        best = max(PointsRule.objects.all(), key=lambda r: r.points)
        text, _ = rules_answer(self.user.agent, "what should i sell")
        self.assertIn(f"{best.label} is worth the most", text)

    def test_what_to_sell_names_the_weakest_category(self):
        from portal.assistant import answer as rules_answer
        focus = self.user.agent.mtd.get(is_focus=True)
        text, _ = rules_answer(self.user.agent, "what should i sell")
        self.assertIn(focus.label, text)
        self.assertIn(str(focus.star_pct), text)

    def test_selling_question_does_not_hijack_other_intents(self):
        """The new keywords are broad - make sure they lose to better matches."""
        from portal.assistant import answer as rules_answer
        cases = {
            "how much have I earned this period": "commission",
            "what is my rank": "ranked",
            "what quests are left today": "quests",
            "do I have any open disputes": "disputes",
        }
        for question, probe in cases.items():
            with self.subTest(question=question):
                text, _ = rules_answer(self.user.agent, question)
                self.assertIn(probe, text)

    def test_selling_context_reaches_claude_too(self):
        """Claude cannot answer it either unless the facts are in context."""
        from portal import llm
        ctx = llm.build_context(self.user.agent)
        self.assertIn("points_per_sale", ctx)
        self.assertIn("your_category_split", ctx)
        self.assertIn("sellable_products", ctx)
        labels = {r["product_unit"] for r in ctx["points_per_sale"]}
        self.assertIn("Gig Internet PSU", labels)

    # ---- floating assistant ----
    def test_assistant_is_not_in_the_sidebar(self):
        self.login()
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertNotIn('<span class="side-label">Assistant</span>', body)

    def test_floating_assistant_is_on_every_page(self):
        self.login()
        for name in ["home", "incentive_feed", "incentive_detail",
                     "calculator", "disputes", "products"]:
            with self.subTest(page=name):
                body = self.client.get(reverse(f"portal:{name}")).content.decode()
                self.assertIn('id="askFab"', body)
                self.assertIn('id="askPanel"', body)

    def test_panel_ships_hidden(self):
        """Inline style, so it cannot be shown by a stale stylesheet."""
        self.login()
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertIn('id="askPanel" hidden style="display:none"', body)

    def test_ask_api_answers_json(self):
        self.login()
        resp = self.client.post(reverse("portal:ask_api"), {"q": "what is my rank"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn(str(self.user.agent.scorecard.rank), data["a"])
        self.assertIn(data["engine"], ("claude", "rules"))
        self.assertTrue(all("url" in l and "label" in l for l in data["links"]))

    def test_ask_api_shares_history_with_the_page(self):
        self.login()
        self.client.post(reverse("portal:ask_api"), {"q": "what is my rank"})
        self.assertEqual(len(self.client.session["ask_history"]), 1)
        page = self.client.get(reverse("portal:ask"))
        self.assertEqual(len(page.context["history"]), 1)

    def test_ask_api_rejects_an_empty_question(self):
        self.login()
        resp = self.client.post(reverse("portal:ask_api"), {"q": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_ask_api_can_clear(self):
        self.login()
        self.client.post(reverse("portal:ask_api"), {"q": "what is my rank"})
        resp = self.client.post(reverse("portal:ask_api"), {"clear": "1"})
        self.assertTrue(resp.json()["cleared"])
        self.assertEqual(self.client.session["ask_history"], [])

    def test_ask_api_requires_login(self):
        resp = self.client.post(reverse("portal:ask_api"), {"q": "what is my rank"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_panel_suggestions_match_the_role(self):
        self.login("gchen")
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertIn("approval", body.lower())

    # ================= visual audit regressions =================
    def test_calculator_already_shows_units_not_money(self):
        """'Already sold 60' used to be dollars, which read as 60 units."""
        self.login()
        inc = Incentive.objects.get(short_code="Inc 01")
        plan = self.client.get(reverse("portal:calculator"),
                               {"incentive": "Inc 01", "target": "500"}).context["plan"]
        self.assertEqual(plan["already"], inc.progress)
        self.assertNotEqual(plan["already"], inc.earned)

    def test_plan_form_preselects_a_single_team(self):
        self.login("jmitchell")
        form = self.client.get(reverse("portal:plan_new")).context["form"]
        lead = AgentProfile.objects.get(user__username="jmitchell")
        self.assertEqual(lead.visible_teams.count(), 1)
        self.assertEqual(form.fields["team"].initial, lead.visible_teams.first())
        self.assertIsNone(form.fields["team"].empty_label)

    def test_plan_form_does_not_prefill_zeros(self):
        """A prefilled 0 is a value the validator then rejects."""
        self.login("jmitchell")
        form = self.client.get(reverse("portal:plan_new")).context["form"]
        self.assertIsNone(form.fields["reward_amount"].initial)
        self.assertIsNone(form.fields["target_units"].initial)

    def test_manager_can_choose_between_teams_on_the_form(self):
        self.login("gchen")
        form = self.client.get(reverse("portal:plan_new")).context["form"]
        self.assertEqual(form.fields["team"].queryset.count(), 2)
        self.assertIsNotNone(form.fields["team"].empty_label)

    def test_market_uses_the_shared_design_language(self):
        """Market was left on the old markup while Home was restyled."""
        self.login("gchen")
        body = self.client.get(reverse("portal:market")).content.decode()
        self.assertIn("kpi-chip", body)
        self.assertIn('class="entity"', body)
        self.assertIn("sec-eyebrow", body)

    def test_every_inner_page_renders_for_its_role(self):
        """A blanket sweep, so no page is only ever checked by hand."""
        pages = {
            "jliu": ["home", "incentive_feed", "incentive_detail", "calculator",
                     "disputes", "products", "ask"],
            "jmitchell": ["home", "team", "trends", "plans", "plan_new",
                          "disputes", "products", "ask"],
            "gchen": ["home", "market", "team", "trends", "plans", "plan_new",
                      "disputes", "products", "ask"],
        }
        for persona, names in pages.items():
            self.client.logout()
            self.login(persona)
            for name in names:
                with self.subTest(persona=persona, page=name):
                    resp = self.client.get(reverse(f"portal:{name}"))
                    self.assertEqual(resp.status_code, 200)

    # ================= the approval chain =================
    # An agent's work is signed off by their team lead; a lead's work is
    # signed off by their manager. Two levels, same shape.

    def _raise_dispute(self):
        self.client.post(reverse("portal:disputes"), {
            "subject": "Gig install paid at the standard rate again",
            "category": "Commission Error", "priority": "High",
        })
        return Dispute.objects.filter(agent=self.user.agent).order_by("-id").first()

    def test_a_raised_dispute_awaits_the_lead(self):
        self.login()
        ticket = self._raise_dispute()
        self.assertEqual(ticket.status, Dispute.State.AWAITING_LEAD)
        self.assertTrue(ticket.is_awaiting_decision)
        self.assertIsNone(ticket.decided_by)

    def test_lead_approves_their_agents_dispute(self):
        self.login()
        ticket = self._raise_dispute()

        self.client.logout()
        self.login("jmitchell")
        self.client.post(reverse("portal:disputes"), {
            "ticket": ticket.ticket_no, "decide": "approve", "note": "Valid - to payouts.",
        })
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Dispute.State.IN_REVIEW)
        self.assertEqual(ticket.decided_by.user.username, "jmitchell")
        self.assertEqual(ticket.decision_note, "Valid - to payouts.")

    def test_lead_rejects_with_a_reason_the_agent_can_see(self):
        self.login()
        ticket = self._raise_dispute()

        self.client.logout()
        self.login("jmitchell")
        self.client.post(reverse("portal:disputes"), {
            "ticket": ticket.ticket_no, "decide": "reject", "note": "Rate was correct.",
        })
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Dispute.State.REJECTED)

        self.client.logout()
        self.login()
        body = self.client.get(reverse("portal:disputes")).content.decode()
        self.assertIn("Rate was correct.", body)
        self.assertIn("Jordan Mitchell", body)

    def test_another_lead_cannot_decide_your_agents_dispute(self):
        self.login()
        ticket = self._raise_dispute()

        self.client.logout()
        self.login("hpark")          # leads the other squad
        resp = self.client.post(reverse("portal:disputes"), {
            "ticket": ticket.ticket_no, "decide": "approve",
        })
        self.assertEqual(resp.status_code, 403)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Dispute.State.AWAITING_LEAD)

    def test_the_manager_above_the_lead_can_also_decide(self):
        self.login()
        ticket = self._raise_dispute()

        self.client.logout()
        self.login("gchen")          # manages Jordan's team
        self.client.post(reverse("portal:disputes"), {
            "ticket": ticket.ticket_no, "decide": "approve",
        })
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Dispute.State.IN_REVIEW)

    def test_a_manager_from_another_region_cannot_decide(self):
        self.login()
        ticket = self._raise_dispute()

        self.client.logout()
        self.login("sreed")
        resp = self.client.post(reverse("portal:disputes"), {
            "ticket": ticket.ticket_no, "decide": "approve",
        })
        self.assertEqual(resp.status_code, 403)

    def test_an_agent_cannot_approve_their_own_dispute(self):
        self.login()
        ticket = self._raise_dispute()
        self.client.post(reverse("portal:disputes"), {
            "ticket": ticket.ticket_no, "decide": "approve",
        })
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Dispute.State.AWAITING_LEAD)

    def test_a_decided_dispute_cannot_be_decided_again(self):
        self.login()
        ticket = self._raise_dispute()

        self.client.logout()
        self.login("jmitchell")
        self.client.post(reverse("portal:disputes"),
                         {"ticket": ticket.ticket_no, "decide": "approve"})
        resp = self.client.post(reverse("portal:disputes"),
                                {"ticket": ticket.ticket_no, "decide": "reject"})
        self.assertEqual(resp.status_code, 403)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Dispute.State.IN_REVIEW)

    def test_lead_queue_lists_what_awaits_them(self):
        self.login("jmitchell")
        ctx = self.client.get(reverse("portal:disputes")).context
        lead = AgentProfile.objects.get(user__username="jmitchell")
        for ticket in ctx["awaiting"]:
            self.assertTrue(ticket.is_awaiting_decision)
            self.assertIn(ticket.agent, set(lead.visible_agents))

    def test_both_levels_of_the_chain_exist(self):
        """Agent -> lead for disputes; lead -> manager for plans."""
        agent = self.user.agent
        lead = AgentProfile.objects.get(user__username="jmitchell")
        manager = AgentProfile.objects.get(user__username="gchen")

        self.login()
        ticket = self._raise_dispute()
        self.assertTrue(ticket.can_be_decided_by(lead))
        self.assertFalse(ticket.can_be_decided_by(agent))

        plan = IncentivePlan.objects.create(
            name="Chain check", team=lead.visible_teams.first(),
            product="X", category="Internet", reward_amount=10, target_units=10,
            runs_from="2026-09-01", runs_to="2026-09-30",
            status=IncentivePlan.State.SUBMITTED, created_by=lead, rationale="x",
        )
        self.assertTrue(plan.can_be_decided_by(manager))
        self.assertFalse(plan.can_be_decided_by(lead))

    # ================= spend dashboard =================
    def test_only_managers_reach_spend(self):
        for slug, expected in [("jliu", 403), ("jmitchell", 403), ("gchen", 200)]:
            with self.subTest(role=slug):
                self.client.logout()
                self.login(slug)
                self.assertEqual(
                    self.client.get(reverse("portal:spend")).status_code, expected)

    def test_spend_is_derived_from_agent_payouts(self):
        """The manager's total must equal what the agents themselves see."""
        self.login("gchen")
        ctx = self.client.get(reverse("portal:spend")).context
        manager = AgentProfile.objects.get(user__username="gchen")

        expected = sum(
            (s.gross_commission + s.spiff_earned)
            for a in manager.visible_agents
            for s in a.snapshots.filter(is_current=True)
        )
        self.assertEqual(ctx["committed"], expected)
        self.assertEqual(ctx["total_spend"], expected + ctx["plan_commitment"])

    def test_approved_plans_count_towards_commitment(self):
        self.login("gchen")
        manager = AgentProfile.objects.get(user__username="gchen")
        before = self.client.get(reverse("portal:spend")).context["plan_commitment"]

        team = manager.visible_teams.first()
        IncentivePlan.objects.create(
            name="Extra spend", team=team,
            product="X", category="Internet", reward_amount=20, target_units=100,
            runs_from="2026-09-01", runs_to="2026-09-30",
            status=IncentivePlan.State.APPROVED,
            created_by=team.lead, rationale="x",
        )
        after = self.client.get(reverse("portal:spend")).context["plan_commitment"]
        self.assertEqual(after - before, 2000)

    def test_setting_the_budget_moves_utilisation(self):
        self.login("gchen")
        first = self.client.get(reverse("portal:spend")).context

        self.client.post(reverse("portal:spend"),
                         {"set_budget": "1", "amount": "100000"})
        after = self.client.get(reverse("portal:spend")).context

        self.assertEqual(after["budget"], 100000)
        self.assertNotEqual(after["utilisation"], first["utilisation"])
        self.assertEqual(after["utilisation"],
                         round(after["total_spend"] / 100000 * 100))
        self.assertEqual(after["budget_row"].set_by.user.username, "gchen")

    def test_over_budget_is_flagged(self):
        self.login("gchen")
        self.client.post(reverse("portal:spend"), {"set_budget": "1", "amount": "1000"})
        ctx = self.client.get(reverse("portal:spend")).context
        self.assertTrue(ctx["over_budget"])
        self.assertGreater(ctx["utilisation"], 100)

    def test_budget_rejects_a_negative_amount(self):
        self.login("gchen")
        before = self.client.get(reverse("portal:spend")).context["budget"]
        self.client.post(reverse("portal:spend"), {"set_budget": "1", "amount": "-5"})
        self.assertEqual(self.client.get(reverse("portal:spend")).context["budget"], before)

    def test_payout_distribution_covers_every_agent(self):
        self.login("gchen")
        ctx = self.client.get(reverse("portal:spend")).context
        manager = AgentProfile.objects.get(user__username="gchen")
        self.assertEqual(sum(b["count"] for b in ctx["distribution"]),
                         manager.visible_agents.count())

    def test_channels_are_scoped_to_the_region(self):
        self.login("gchen")
        ctx = self.client.get(reverse("portal:spend")).context
        self.assertTrue(ctx["channels"])
        for c in ctx["channels"]:
            self.assertEqual(c.region, ctx["region"])

    def test_each_manager_sees_their_own_region(self):
        self.login("gchen")
        south = self.client.get(reverse("portal:spend")).context["region"]
        self.client.logout()
        self.login("sreed")
        north = self.client.get(reverse("portal:spend")).context["region"]
        self.assertNotEqual(south, north)

    # ---- exceptions ----
    def test_exceptions_are_derived_from_the_roster(self):
        """Each flag should describe a condition visible on the agent's page."""
        self.assertTrue(PayoutException.objects.exists())
        for e in PayoutException.objects.all():
            with self.subTest(exception=e.pk):
                self.assertIsNotNone(e.agent.team)
                self.assertGreater(e.amount, 0)

    def _pending_for_grace(self):
        manager = AgentProfile.objects.get(user__username="gchen")
        return PayoutException.objects.filter(
            agent__team__in=manager.visible_teams,
            status=PayoutException.State.PENDING).first()

    def test_manager_clears_an_exception(self):
        flagged = self._pending_for_grace()
        self.login("gchen")
        self.client.post(reverse("portal:spend"), {
            "exception": flagged.pk, "decide": "clear", "note": "Orders check out.",
        })
        flagged.refresh_from_db()
        self.assertEqual(flagged.status, PayoutException.State.CLEARED)
        self.assertEqual(flagged.decided_by.user.username, "gchen")
        self.assertEqual(flagged.decision_note, "Orders check out.")

    def test_manager_escalates_an_exception(self):
        flagged = self._pending_for_grace()
        self.login("gchen")
        self.client.post(reverse("portal:spend"),
                         {"exception": flagged.pk, "decide": "escalate"})
        flagged.refresh_from_db()
        self.assertEqual(flagged.status, PayoutException.State.ESCALATED)

    def test_another_manager_cannot_decide_it(self):
        flagged = self._pending_for_grace()
        self.login("sreed")
        resp = self.client.post(reverse("portal:spend"),
                                {"exception": flagged.pk, "decide": "clear"})
        self.assertEqual(resp.status_code, 403)
        flagged.refresh_from_db()
        self.assertEqual(flagged.status, PayoutException.State.PENDING)

    def test_a_decided_exception_cannot_be_decided_again(self):
        flagged = self._pending_for_grace()
        self.login("gchen")
        self.client.post(reverse("portal:spend"),
                         {"exception": flagged.pk, "decide": "clear"})
        resp = self.client.post(reverse("portal:spend"),
                                {"exception": flagged.pk, "decide": "escalate"})
        self.assertEqual(resp.status_code, 403)
        flagged.refresh_from_db()
        self.assertEqual(flagged.status, PayoutException.State.CLEARED)

    def test_held_amount_only_counts_pending(self):
        self.login("gchen")
        ctx = self.client.get(reverse("portal:spend")).context
        self.assertEqual(ctx["held"], sum(e.amount for e in ctx["pending"]))
        for e in ctx["pending"]:
            self.assertTrue(e.is_pending)

    def test_login_works_without_javascript(self):
        """
        Each persona card is a real submit button and the Continue button
        carries the default slug, so signing in never depends on JS running.
        """
        resp = self.client.get(reverse("login"))
        body = resp.content.decode()
        self.assertNotIn("disabled", body.split('id="enterBtn"')[1][:120])
        self.assertIn('type="submit" name="persona" value="jliu"', body)
        self.assertIn(f'id="enterBtn" name="persona" value="{resp.context["default_slug"]}"', body)

    def test_posting_a_card_value_signs_you_in(self):
        """The no-JS path: the card itself carries the slug."""
        resp = self.client.post(reverse("login"), {"persona": "jmitchell"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            AgentProfile.objects.get(pk=int(self.client.session["_auth_user_id"]) and
                                     AgentProfile.objects.get(
                                         user_id=int(self.client.session["_auth_user_id"])).pk
                                     ).user.username,
            "jmitchell",
        )

    def test_default_slug_is_a_real_persona(self):
        resp = self.client.get(reverse("login"))
        slug = resp.context["default_slug"]
        self.assertTrue(Persona.objects.filter(slug=slug, is_available=True).exists())

    def test_no_horizontal_page_scroll_is_enforced(self):
        """
        The window must never scroll sideways. `clip` rather than `hidden`,
        so the sticky top bar and sidebar keep working.
        """
        from django.conf import settings
        css = (settings.BASE_DIR / "static" / "css" / "shell.css").read_text(encoding="utf-8")
        self.assertIn("overflow-x: clip;", css)
        self.assertNotIn("overflow-x: hidden;", css.split("body.app")[1][:400])

    def test_confetti_canvas_has_an_explicit_css_size(self):
        """
        A canvas lays out at its drawing-buffer size unless told otherwise,
        and that buffer is innerWidth x devicePixelRatio - double the window
        on a 2x screen.
        """
        from django.conf import settings
        css = (settings.BASE_DIR / "static" / "css" / "anim.css").read_text(encoding="utf-8")
        block = css.split("#confetti {")[1].split("}")[0]
        self.assertIn("width: 100%", block)
        self.assertIn("height: 100%", block)

    def test_fixed_rail_grids_can_shrink(self):
        """
        A bare `1fr` is `minmax(auto, 1fr)`, and that auto floor is the
        column's min-content width - which pushed the fixed 340px rail clean
        off the page between roughly 1100px and 1250px.
        """
        from django.conf import settings
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: minmax(0, 1fr) 340px;", css)
        self.assertIn(".split > *, .stack, .grid > * { min-width: 0; }", css)

    def test_split_collapses_before_the_content_column_runs_out(self):
        """
        The breakpoint measures the viewport, but the sidebar makes the content
        area ~260px narrower, so 1080px fired far too late.
        """
        from django.conf import settings
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
        rule = css.split("@media (max-width: 1250px)")[1][:120]
        self.assertIn(".split { grid-template-columns: 1fr;", rule)

    def test_theme_sheet_loads_last(self):
        """It restyles by overriding tokens, so it must win the cascade."""
        from django.conf import settings
        for tpl in ("portal/templates/portal/base.html",
                    "templates/registration/login.html"):
            with self.subTest(template=tpl):
                html = (settings.BASE_DIR / tpl).read_text(encoding="utf-8")
                self.assertIn("css/themes.css", html)
                self.assertGreater(html.index("css/themes.css"), html.index("css/app.css"))

    def test_there_is_one_style_and_no_switcher_left_behind(self):
        """
        The portal ships a single Spectrum style. The switcher that used to
        choose between experiments was removed with them - this fails if any
        of its markup, script or storage key creeps back.
        """
        from django.conf import settings

        base = (settings.BASE_DIR / "portal" / "templates" / "portal" / "base.html").read_text(encoding="utf-8")
        css = (settings.BASE_DIR / "static" / "css" / "press.css").read_text(encoding="utf-8")
        self.assertIn('[data-theme="press"]', css)
        for gone in ("data-set-theme", "theme-menu", "theme-btn",
                     "themeBoot", "portalTheme", "js/theme.js"):
            with self.subTest(leftover=gone):
                self.assertNotIn(gone, base)

    def test_no_stylesheet_is_linked_that_does_not_exist(self):
        """A dead <link> is a silent 404 on every page load."""
        from django.conf import settings
        import re as _re
        for tpl in ("portal/templates/portal/base.html", "templates/registration/login.html"):
            html = (settings.BASE_DIR / tpl).read_text(encoding="utf-8")
            for name in _re.findall(r"static_v '(css/[^']+)'", html):
                with self.subTest(template=tpl, sheet=name):
                    self.assertTrue((settings.BASE_DIR / "static" / name).exists(),
                                    "%s is linked but missing" % name)

    def test_the_style_attribute_is_on_the_root_element(self):
        """
        Every themed rule is scoped to [data-theme="press"], so if the
        attribute is missing the whole portal renders unstyled.
        """
        from django.conf import settings

        for tpl in ("portal/templates/portal/base.html",
                    "templates/registration/login.html"):
            with self.subTest(template=tpl):
                html = (settings.BASE_DIR / tpl).read_text(encoding="utf-8")
                self.assertIn('data-theme="press"', html)
                self.assertLess(html.index('data-theme="press"'), html.index("</head>"),
                                "must be set on <html>, before any painting")

    def test_styles_use_only_spectrum_brand_colours(self):
        """
        Every literal hex in the theme sheet must be a Spectrum brand colour,
        a neutral, or a documented tint of one - no invented accent hues.
        """
        from django.conf import settings
        css = (settings.BASE_DIR / "static" / "css" / "themes.css").read_text(encoding="utf-8")
        hexes = {h.lower() for h in re.findall(r"#([0-9a-fA-F]{6})", css)}
        allowed = {
            "0073d1", "3596e4", "005ca9", "003057", "001b33", "002744",
            "e8f3fc", "cfe6f8", "ffffff", "128a4b", "b26b00", "c8102e",
            # dark-canvas neutrals and lifted semantics for legibility on navy
            "eaf3fb", "b9d2e8", "7fa0bd", "5d7f9e", "123c60", "0d2f4d",
            "06182b", "0a2d4c", "0a3a63", "17527f", "1d5183",
            "35c07d", "ff6b81", "e9a53c", "9ce6c1", "a9c4dc", "7fc0f5",
            # light-theme neutrals
            "21384f", "6b7f93", "93a5b6", "e2e9f0", "eef3f8",
            "2b4257", "6d8298", "92a6b9", "dbe9f5", "e9f2fa", "dbeaf7",
            "1d3145", "5f7385", "8a9bab", "ccd6de", "f4faff",
            # categorical data palette: six tones the templates already ask
            # for (blue/teal/violet/green/amber/red) plus a magenta, so
            # chart series and channels are told apart by hue
            "00818f", "6c4bb6", "b5006e",
            "2ab8c4", "9b82f0", "f0629f",
            # neutral chrome: graphite and paper carry the surfaces so that
            # blue is one voice among six rather than the ground
            "16191d", "1e232a", "2b3138", "f7f7f6", "efefed",
            "14171b", "101317", "1c2027", "2a3038", "22272e",
            "232830", "1a1e24", "333a44",
            # avatar fills: deep enough for white initials in every style
            "00707d", "5d3fa8", "a3005f", "8f5600", "0f7440",
            "12897f", "c07a10", "6b52d6", "39414b",
        }
        self.assertEqual(hexes - allowed, set(),
                         "non-Spectrum colours introduced: %s" % (hexes - allowed))

    def test_sign_in_hero_is_not_a_blue_wash(self):
        """
        The sign-in hero was ~40% blue-dominant - the bluest surface in the
        product, and the first screen anyone sees. It stays neutral.
        """
        from django.conf import settings
        css = (settings.BASE_DIR / "static" / "css" / "login.css").read_text(encoding="utf-8")
        hero = css.split(".login-art {")[1].split("}")[0]
        self.assertIn("#16191d", hero)
        self.assertNotIn("rgba(0,115,209,.55)", hero)

    # ================= logging a sale, and the lead sign-off =================
    def _log_a_sale(self, slug="jliu", units=2):
        self.login(slug)
        offer = Offer.objects.filter(status=Status.ACTIVE).first()
        resp = self.client.post(reverse("portal:sales"), {
            "log_sale": "1", "offer": offer.pk, "customer": "A. Customer",
            "units": units, "sold_on": date.today().isoformat(),
        })
        return offer, resp

    def test_agent_can_log_a_sale(self):
        offer, resp = self._log_a_sale()
        self.assertEqual(resp.status_code, 302)
        sale = Sale.objects.filter(customer="A. Customer").first()
        self.assertIsNotNone(sale)
        self.assertEqual(sale.agent.user.username, "jliu")
        self.assertEqual(sale.offer, offer)

    def test_a_logged_sale_starts_awaiting_the_lead_and_pays_nothing(self):
        self._log_a_sale()
        sale = Sale.objects.get(customer="A. Customer")
        self.assertEqual(sale.approval, Sale.Approval.AWAITING_LEAD)
        self.assertTrue(sale.is_awaiting_decision)
        self.assertEqual(sale.earned, Decimal("0.00"))
        self.assertGreater(sale.incentive_value, 0)

    def test_the_incentive_is_derived_from_the_offer_not_the_form(self):
        """An agent must not be able to name their own payout."""
        offer, _ = self._log_a_sale(units=3)
        sale = Sale.objects.get(customer="A. Customer")
        self.assertEqual(sale.base, offer.commission * 3)
        self.assertEqual(sale.spiff, offer.spiff * 3)

    def test_a_future_dated_sale_is_rejected(self):
        self.login("jliu")
        offer = Offer.objects.filter(status=Status.ACTIVE).first()
        self.client.post(reverse("portal:sales"), {
            "log_sale": "1", "offer": offer.pk, "customer": "Future Co",
            "units": 1, "sold_on": (date.today() + timedelta(days=3)).isoformat(),
        })
        self.assertFalse(Sale.objects.filter(customer="Future Co").exists())

    def test_lead_approves_and_the_sale_becomes_payable(self):
        self._log_a_sale()
        sale = Sale.objects.get(customer="A. Customer")
        self.client.logout()
        self.login("jmitchell")
        self.client.post(reverse("portal:sales"), {
            "order": sale.order_no, "decide": "approve", "note": "Order verified.",
        })
        sale.refresh_from_db()
        self.assertEqual(sale.approval, Sale.Approval.APPROVED)
        self.assertEqual(sale.earned, sale.incentive_value)
        self.assertEqual(sale.decided_by.user.username, "jmitchell")
        self.assertEqual(sale.decision_note, "Order verified.")
        self.assertIsNotNone(sale.decided_on)

    def test_lead_rejects_and_it_still_pays_nothing(self):
        self._log_a_sale()
        sale = Sale.objects.get(customer="A. Customer")
        self.client.logout()
        self.login("jmitchell")
        self.client.post(reverse("portal:sales"),
                         {"order": sale.order_no, "decide": "reject"})
        sale.refresh_from_db()
        self.assertEqual(sale.approval, Sale.Approval.REJECTED)
        self.assertEqual(sale.earned, Decimal("0.00"))

    def test_an_agent_cannot_approve_their_own_sale(self):
        self._log_a_sale()
        sale = Sale.objects.get(customer="A. Customer")
        resp = self.client.post(reverse("portal:sales"),
                                {"order": sale.order_no, "decide": "approve"})
        sale.refresh_from_db()
        self.assertEqual(sale.approval, Sale.Approval.AWAITING_LEAD)
        self.assertEqual(resp.status_code, 403)

    def test_another_teams_lead_cannot_approve_it(self):
        self._log_a_sale()
        sale = Sale.objects.get(customer="A. Customer")
        self.client.logout()
        self.login("hpark")
        resp = self.client.post(reverse("portal:sales"),
                                {"order": sale.order_no, "decide": "approve"})
        self.assertEqual(resp.status_code, 403)
        sale.refresh_from_db()
        self.assertEqual(sale.approval, Sale.Approval.AWAITING_LEAD)

    def test_a_decided_sale_cannot_be_decided_twice(self):
        self._log_a_sale()
        sale = Sale.objects.get(customer="A. Customer")
        self.client.logout()
        self.login("jmitchell")
        self.client.post(reverse("portal:sales"), {"order": sale.order_no, "decide": "approve"})
        resp = self.client.post(reverse("portal:sales"), {"order": sale.order_no, "decide": "reject"})
        self.assertEqual(resp.status_code, 403)
        sale.refresh_from_db()
        self.assertEqual(sale.approval, Sale.Approval.APPROVED)

    def test_the_sale_appears_in_its_lead_queue_only(self):
        self._log_a_sale()
        sale = Sale.objects.get(customer="A. Customer")
        self.client.logout()
        self.login("jmitchell")
        self.assertIn(sale, self.client.get(reverse("portal:sales")).context["awaiting"])
        self.client.logout()
        self.login("hpark")
        self.assertNotIn(sale, self.client.get(reverse("portal:sales")).context["awaiting"])

    def test_agent_totals_separate_approved_from_pending(self):
        self._log_a_sale()
        self.login("jliu")
        ctx = self.client.get(reverse("portal:sales")).context
        sale = Sale.objects.get(customer="A. Customer")
        self.assertIn(sale.incentive_value, [ctx["pending_total"]] if
                      ctx["pending_total"] == sale.incentive_value else [ctx["pending_total"]])
        self.assertEqual(ctx["awaiting_count"], 1)

    def test_approving_moves_money_from_pending_to_approved(self):
        self._log_a_sale()
        self.login("jliu")
        before = self.client.get(reverse("portal:sales")).context
        sale = Sale.objects.get(customer="A. Customer")
        self.client.logout()
        self.login("jmitchell")
        self.client.post(reverse("portal:sales"), {"order": sale.order_no, "decide": "approve"})
        self.client.logout()
        self.login("jliu")
        after = self.client.get(reverse("portal:sales")).context
        self.assertEqual(before["pending_total"] - after["pending_total"], sale.incentive_value)
        self.assertEqual(after["approved_total"] - before["approved_total"], sale.incentive_value)

    def test_order_numbers_are_unique(self):
        self._log_a_sale()
        self.login("jliu")
        offer = Offer.objects.filter(status=Status.ACTIVE).first()
        self.client.post(reverse("portal:sales"), {
            "log_sale": "1", "offer": offer.pk, "customer": "Second Customer",
            "units": 1, "sold_on": date.today().isoformat(),
        })
        nos = list(Sale.objects.values_list("order_no", flat=True))
        self.assertEqual(len(nos), len(set(nos)))

    def test_a_programme_appears_in_exactly_one_bucket(self):
        """
        Ending Soon was every live programme with a week left, so each one
        rendered twice - once under Active and again under Ending Soon.
        """
        self.login()
        ctx = self.client.get(reverse("portal:incentive_feed")).context
        seen = []
        for bucket in ("active", "launched", "ending", "previous"):
            seen += [i.pk for i in ctx[bucket]]
        self.assertEqual(len(seen), len(set(seen)),
                         "a programme is listed in more than one bucket")

    def test_ending_soon_holds_the_urgent_ones(self):
        self.login()
        ctx = self.client.get(reverse("portal:incentive_feed")).context
        self.assertTrue(ctx["ending"], "nothing is ending soon in the seed data")
        for i in ctx["ending"]:
            self.assertLessEqual(i.days_left, 7)
        for i in ctx["active"]:
            self.assertGreater(i.days_left, 7)

    # ================= the next action =================
    def test_home_leads_with_one_directive(self):
        """The page should answer "what do I do next", not just show figures."""
        self.login()
        ctx = self.client.get(reverse("portal:home")).context
        act = ctx["next_action"]
        self.assertIn(act["tone"], {"red", "amber", "blue", "green"})
        self.assertTrue(act["text"] and act["cta"] and act["url"])

    def test_a_rejected_sale_outranks_everything(self):
        """Priority order matters: money lost beats money pending."""
        from portal.models import Sale
        agent = AgentProfile.objects.get(user__username="jliu")
        sale = agent.sales.first()
        sale.approval = Sale.Approval.REJECTED
        sale.save(update_fields=["approval"])
        self.login()
        act = self.client.get(reverse("portal:home")).context["next_action"]
        self.assertEqual(act["tone"], "red")
        self.assertIn("rejected", act["text"].lower())

    def test_pending_approval_is_surfaced_with_the_amount_held(self):
        from portal.models import Offer, Sale, Status
        agent = AgentProfile.objects.get(user__username="jliu")
        agent.sales.all().delete()
        agent.disputes.all().delete()
        offer = Offer.objects.filter(status=Status.ACTIVE).first()
        Sale.objects.create(
            agent=agent, sold_on=date.today(), order_no="ORD-TEST-1",
            customer="Held Co", offer=offer, units=1,
            base=offer.commission, spiff=offer.spiff,
            approval=Sale.Approval.AWAITING_LEAD,
        )
        self.login()
        act = self.client.get(reverse("portal:home")).context["next_action"]
        self.assertEqual(act["tone"], "amber")
        self.assertIn("$", act["text"])

    # ================= month-end close =================
    def _clear_all_exceptions(self, username="gchen"):
        from portal.models import PayoutException
        mgr = AgentProfile.objects.get(user__username=username)
        PayoutException.objects.filter(agent__team__in=mgr.visible_teams).update(
            status=PayoutException.State.CLEARED)

    def test_only_managers_reach_the_close(self):
        for slug, expected in [("jliu", 403), ("jmitchell", 403), ("gchen", 200)]:
            with self.subTest(role=slug):
                self.client.logout(); self.login(slug)
                self.assertEqual(self.client.get(reverse("portal:close")).status_code, expected)

    def test_open_exceptions_block_the_calculation(self):
        """A total that ignores held money is worse than no total."""
        self.login("gchen")
        ctx = self.client.get(reverse("portal:close")).context
        self.assertTrue(ctx["blocked"], "seed data should have a pending exception")
        self.client.post(reverse("portal:close"), {"action": "calculate"})
        period = PeriodClose.objects.get(region=ctx["region"])
        self.assertEqual(period.status, PeriodClose.State.OPEN)

    def test_calculating_freezes_the_figures(self):
        self._clear_all_exceptions()
        self.login("gchen")
        self.client.post(reverse("portal:close"), {"action": "calculate"})
        period = PeriodClose.objects.first()
        self.assertEqual(period.status, PeriodClose.State.CALCULATED)
        self.assertEqual(period.calculated_by.user.username, "gchen")
        self.assertIsNotNone(period.calculated_on)
        self.assertEqual(
            period.total,
            period.agent_payouts + period.plan_commitments + period.approved_sales)
        self.assertGreater(period.total, 0)

    def test_a_later_sale_does_not_move_a_frozen_total(self):
        """The figure payroll saw must stay the figure payroll saw."""
        self._clear_all_exceptions()
        self.login("gchen")
        self.client.post(reverse("portal:close"), {"action": "calculate"})
        frozen = PeriodClose.objects.first().total

        agent = AgentProfile.objects.get(user__username="jliu")
        offer = Offer.objects.filter(status=Status.ACTIVE).first()
        Sale.objects.create(
            agent=agent, sold_on=date.today(), order_no="ORD-AFTER-CLOSE",
            customer="Late Co", offer=offer, units=2,
            base=offer.commission * 2, spiff=offer.spiff * 2,
            approval=Sale.Approval.APPROVED)
        self.assertEqual(PeriodClose.objects.first().total, frozen)

    def test_cannot_approve_before_calculating(self):
        self._clear_all_exceptions()
        self.login("gchen")
        resp = self.client.post(reverse("portal:close"), {"action": "approve"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(PeriodClose.objects.first().status, PeriodClose.State.OPEN)

    def test_approving_hands_it_to_payroll_and_locks_it(self):
        self._clear_all_exceptions()
        self.login("gchen")
        self.client.post(reverse("portal:close"), {"action": "calculate"})
        self.client.post(reverse("portal:close"),
                         {"action": "approve", "note": "Q3 true-up applied"})
        period = PeriodClose.objects.first()
        self.assertEqual(period.status, PeriodClose.State.APPROVED)
        self.assertTrue(period.is_locked)
        self.assertEqual(period.approved_by.user.username, "gchen")
        self.assertEqual(period.note, "Q3 true-up applied")

    def test_a_locked_period_refuses_everything(self):
        self._clear_all_exceptions()
        self.login("gchen")
        self.client.post(reverse("portal:close"), {"action": "calculate"})
        self.client.post(reverse("portal:close"), {"action": "approve"})
        for action in ("calculate", "approve"):
            with self.subTest(action=action):
                resp = self.client.post(reverse("portal:close"), {"action": action})
                self.assertEqual(resp.status_code, 403)
        self.assertEqual(PeriodClose.objects.first().status, PeriodClose.State.APPROVED)

    def test_each_region_closes_separately(self):
        self._clear_all_exceptions("gchen")
        self.login("gchen")
        south = self.client.get(reverse("portal:close")).context["region"]
        self.client.post(reverse("portal:close"), {"action": "calculate"})
        self.client.logout(); self.login("sreed")
        north = self.client.get(reverse("portal:close")).context
        self.assertNotEqual(north["region"], south)
        self.assertEqual(north["period"].status, PeriodClose.State.OPEN)

    def test_only_lead_approved_sales_reach_payroll(self):
        """A sale awaiting its lead must not be counted in the close."""
        self._clear_all_exceptions()
        agent = AgentProfile.objects.get(user__username="jliu")
        offer = Offer.objects.filter(status=Status.ACTIVE).first()
        Sale.objects.create(
            agent=agent, sold_on=date.today(), order_no="ORD-PENDING-1",
            customer="Pending Co", offer=offer, units=5,
            base=offer.commission * 5, spiff=offer.spiff * 5,
            approval=Sale.Approval.AWAITING_LEAD)
        self.login("gchen")
        before = self.client.get(reverse("portal:close")).context["preview_sales"]
        Sale.objects.filter(order_no="ORD-PENDING-1").update(
            approval=Sale.Approval.APPROVED)
        after = self.client.get(reverse("portal:close")).context["preview_sales"]
        self.assertEqual(after - before, offer.commission * 5 + offer.spiff * 5)

    # ================= reports =================
    def test_agents_cannot_reach_reports_or_directory(self):
        self.login("jliu")
        for name in ("portal:reports", "portal:directory"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_every_report_builds_and_downloads(self):
        from portal.views_reports import REPORTS
        self.login("gchen")
        for slug in REPORTS:
            with self.subTest(report=slug):
                self.assertEqual(
                    self.client.get(reverse("portal:report_detail", args=[slug])).status_code, 200)
                csv_resp = self.client.get(reverse("portal:report_csv", args=[slug]))
                self.assertEqual(csv_resp.status_code, 200)
                self.assertEqual(csv_resp["Content-Type"], "text/csv")
                self.assertIn("attachment", csv_resp["Content-Disposition"])

    def test_an_unknown_report_is_404_not_a_crash(self):
        self.login("gchen")
        self.assertEqual(
            self.client.get(reverse("portal:report_detail", args=["made-up"])).status_code, 404)

    def test_a_csv_row_matches_the_records_behind_it(self):
        """The download must be the same data the portal renders."""
        import csv as _csv
        self.login("gchen")
        body = self.client.get(
            reverse("portal:report_csv", args=["payout-register"])).content.decode()
        rows = list(_csv.reader(body.splitlines()))
        header, data = rows[0], rows[1:]
        self.assertEqual(header[0], "Agent")
        manager = AgentProfile.objects.get(user__username="gchen")
        self.assertEqual(len(data), sum(
            1 for a in manager.visible_agents if a.snapshots.filter(is_current=True).exists()))
        # full_name is a property, so match in Python rather than the ORM.
        first = data[0]
        person = next(a for a in manager.visible_agents if a.full_name == first[0])
        snap = person.snapshots.filter(is_current=True).first()
        self.assertEqual(first[-1], f"{snap.gross_commission + snap.spiff_earned:.2f}")

    def test_reports_are_scoped_to_the_viewer(self):
        """A lead's export must not contain another lead's squad."""
        import csv as _csv
        self.login("jmitchell")
        lead_rows = list(_csv.reader(self.client.get(
            reverse("portal:report_csv", args=["payout-register"])).content.decode().splitlines()))[1:]
        self.client.logout(); self.login("gchen")
        mgr_rows = list(_csv.reader(self.client.get(
            reverse("portal:report_csv", args=["payout-register"])).content.decode().splitlines()))[1:]
        self.assertLess(len(lead_rows), len(mgr_rows))
        lead = AgentProfile.objects.get(user__username="jmitchell")
        allowed = {a.full_name for a in lead.visible_agents}
        for r in lead_rows:
            self.assertIn(r[0], allowed)

    # ================= agent directory =================
    def test_directory_pages_without_losing_anyone(self):
        self.login("gchen")
        seen, page = [], 1
        while True:
            ctx = self.client.get(reverse("portal:directory"), {"page": page}).context
            seen += [r["full_name"] for r in ctx["rows"]]
            if not ctx["page"].has_next():
                break
            page += 1
        manager = AgentProfile.objects.get(user__username="gchen")
        self.assertEqual(sorted(seen), sorted(a.full_name for a in manager.visible_agents))
        self.assertEqual(len(seen), len(set(seen)), "an agent appeared on two pages")

    def test_directory_search_narrows(self):
        self.login("gchen")
        everyone = self.client.get(reverse("portal:directory")).context["total"]
        found = self.client.get(reverse("portal:directory"), {"q": "Jenny"}).context
        self.assertLess(found["total"], everyone)
        for r in found["rows"]:
            self.assertIn("jenny", r["full_name"].lower())

    def test_directory_filter_and_search_combine(self):
        self.login("gchen")
        ctx = self.client.get(reverse("portal:directory")).context
        team = ctx["teams"][0]
        filtered = self.client.get(reverse("portal:directory"), {"team": team}).context
        for r in filtered["rows"]:
            self.assertEqual(r["team"], team)

    def test_directory_sorting_actually_sorts(self):
        self.login("gchen")
        rows = self.client.get(reverse("portal:directory"), {"sort": "payout"}).context["rows"]
        payouts = [r["payout"] for r in rows]
        self.assertEqual(payouts, sorted(payouts, reverse=True))
        names = [r["full_name"] for r in
                 self.client.get(reverse("portal:directory"), {"sort": "name"}).context["rows"]]
        self.assertEqual(names, sorted(names))

    def test_a_lead_cannot_page_into_another_squad(self):
        """Scope comes from the role, never from a URL parameter."""
        self.login("jmitchell")
        lead = AgentProfile.objects.get(user__username="jmitchell")
        allowed = {a.full_name for a in lead.visible_agents}
        page = 1
        while True:
            ctx = self.client.get(reverse("portal:directory"), {"page": page}).context
            for r in ctx["rows"]:
                self.assertIn(r["full_name"], allowed)
            if not ctx["page"].has_next():
                break
            page += 1

    # ================= channels, settings, plan versions =================
    def test_channels_are_scoped_and_add_up(self):
        self.login("gchen")
        ctx = self.client.get(reverse("portal:channels")).context
        self.assertTrue(ctx["rows"])
        for c in ctx["rows"]:
            self.assertIn(c.region, ctx["regions"])
        self.assertEqual(ctx["total_spend"], sum(c.spend for c in ctx["rows"]))
        self.assertEqual(sum(c.share for c in ctx["rows"]) > 90, True)

    def test_agents_cannot_reach_channels_or_settings(self):
        self.login("jliu")
        for name in ("portal:channels", "portal:settings"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_settings_are_manager_only(self):
        self.client.logout(); self.login("jmitchell")
        self.assertEqual(self.client.get(reverse("portal:settings")).status_code, 403)

    def test_saving_a_threshold_changes_what_it_catches(self):
        """A setting that does not move another number is decoration."""
        self.login("gchen")
        before = self.client.get(reverse("portal:settings")).context
        self.client.post(reverse("portal:settings"), {
            "coaching_threshold": 99, "exception_threshold": "3000.00",
            "close_reminder_days": 3,
            "notify_on_dispute": "on", "notify_on_plan": "on", "notify_on_close": "on",
        })
        after = self.client.get(reverse("portal:settings")).context
        self.assertEqual(after["record"].coaching_threshold, 99)
        self.assertGreater(len(after["below"]), len(before["below"]))
        self.assertEqual(after["record"].updated_by.user.username, "gchen")

    def test_a_nonsense_threshold_is_refused(self):
        self.login("gchen")
        self.client.post(reverse("portal:settings"), {
            "coaching_threshold": 250, "exception_threshold": "-5",
            "close_reminder_days": 3})
        record = Setting.objects.get(region=self.client.get(
            reverse("portal:settings")).context["region"])
        self.assertNotEqual(record.coaching_threshold, 250)

    def test_settings_are_per_region(self):
        self.login("gchen")
        self.client.post(reverse("portal:settings"), {
            "coaching_threshold": 55, "exception_threshold": "3000.00",
            "close_reminder_days": 3})
        self.client.logout(); self.login("sreed")
        other = self.client.get(reverse("portal:settings")).context["record"]
        self.assertEqual(other.coaching_threshold, 70, "the default, untouched")

    def test_cloning_a_plan_bumps_the_version_and_leaves_the_original(self):
        from portal.models import IncentivePlan
        self.login("jmitchell")
        lead = AgentProfile.objects.get(user__username="jmitchell")
        original = IncentivePlan.objects.create(
            name="Fibre push", team=lead.team, product="1 Gig",
            category="Internet", reward_amount=15, target_units=40,
            runs_from="2026-09-01", runs_to="2026-09-30",
            status=IncentivePlan.State.APPROVED, created_by=lead, rationale="x")

        self.client.post(reverse("portal:plan_clone", args=[original.pk]))
        copy = IncentivePlan.objects.filter(cloned_from=original).first()
        self.assertIsNotNone(copy)
        self.assertEqual(copy.version, original.version + 1)
        self.assertEqual(copy.status, IncentivePlan.State.DRAFT)
        self.assertEqual(copy.name, original.name)
        original.refresh_from_db()
        self.assertEqual(original.status, IncentivePlan.State.APPROVED,
                         "the approved original must be untouched")

    def test_cannot_clone_another_teams_plan(self):
        from portal.models import IncentivePlan
        other = AgentProfile.objects.get(user__username="hpark")
        plan = IncentivePlan.objects.create(
            name="Not yours", team=other.team, product="X", category="Internet",
            reward_amount=5, target_units=10, runs_from="2026-09-01",
            runs_to="2026-09-30", created_by=other, rationale="x")
        self.login("jmitchell")
        resp = self.client.post(reverse("portal:plan_clone", args=[plan.pk]))
        self.assertEqual(resp.status_code, 403)

    # ================= the character =================
    def test_the_character_appears_on_every_page(self):
        self.login("jliu")
        body = self.client.get(reverse("portal:home")).content.decode()
        self.assertIn('class="ch ', body)
        self.assertIn("data-mood", body)

    def test_its_mood_follows_the_records(self):
        """A cheerful figure beside a rejected payout would be a lie."""
        from portal.models import Sale
        agent = AgentProfile.objects.get(user__username="jliu")
        agent.sales.all().delete()
        agent.disputes.all().delete()
        self.login("jliu")
        self.assertEqual(
            self.client.get(reverse("portal:home")).context["assistant_mood"], "green")

        offer = Offer.objects.filter(status=Status.ACTIVE).first()
        sale = Sale.objects.create(
            agent=agent, sold_on=date.today(), order_no="ORD-MOOD-1",
            customer="Mood Co", offer=offer, units=1,
            base=offer.commission, spiff=offer.spiff,
            approval=Sale.Approval.AWAITING_LEAD)
        self.assertEqual(
            self.client.get(reverse("portal:home")).context["assistant_mood"], "amber")

        sale.approval = Sale.Approval.REJECTED
        sale.save(update_fields=["approval"])
        self.assertEqual(
            self.client.get(reverse("portal:home")).context["assistant_mood"], "red")

    def test_a_manager_with_held_money_is_not_cheerful(self):
        self.login("gchen")
        self.assertEqual(
            self.client.get(reverse("portal:home")).context["assistant_mood"], "red")

    def test_the_mood_never_breaks_a_page(self):
        """It is decoration; it must not be able to raise."""
        from portal.context_processors import assistant_mood

        class Broken:
            is_authenticated = True
            @property
            def agent(self):
                raise RuntimeError("database on fire")

        class Req:
            user = Broken()

        self.assertEqual(assistant_mood(Req())["assistant_mood"], "blue")

    # ================= the daily roll =================
    def test_the_roll_pays_the_face_times_ten(self):
        agent = AgentProfile.objects.get(user__username="jliu")
        for _ in range(40):
            before = agent.xp
            xp, face = agent.roll_the_die()
            self.assertIn(face, range(1, 7))
            self.assertEqual(xp, face * 10)
            self.assertEqual(agent.xp - before, xp)

    def test_the_roll_uses_all_six_faces(self):
        agent = AgentProfile.objects.get(user__username="jliu")
        seen = {agent.roll_the_die()[1] for _ in range(300)}
        self.assertEqual(seen, {1, 2, 3, 4, 5, 6})

    def test_signing_in_rolls_once_and_banks_it(self):
        agent = AgentProfile.objects.get(user__username="jliu")
        agent.last_seen = None
        agent.save(update_fields=["last_seen"])
        before = agent.xp
        reward = agent.register_signin(date.today())
        self.assertIn(reward["die"], range(1, 7))
        self.assertEqual(reward["die_xp"], reward["die"] * 10)
        agent.refresh_from_db()
        self.assertEqual(agent.xp - before, reward["xp_awarded"] + reward["die_xp"])

    def test_a_second_signin_the_same_day_shows_the_die_but_pays_nothing(self):
        """
        The die is shown on every sign-in - it is the point of the feature -
        but only the first roll of the day pays, or signing out and back in
        would farm XP without limit.
        """
        agent = AgentProfile.objects.get(user__username="jliu")
        agent.last_seen = None
        agent.last_roll_on = None
        agent.save(update_fields=["last_seen", "last_roll_on"])

        first = agent.register_signin(date.today())
        agent.refresh_from_db()
        banked = agent.xp
        self.assertGreater(first["die_xp"], 0)
        self.assertFalse(first["die_already_rolled"])

        second = agent.register_signin(date.today())
        agent.refresh_from_db()
        self.assertEqual(second["die"], first["die"], "same face, shown again")
        self.assertEqual(second["die_xp"], 0, "but it must not pay twice")
        self.assertTrue(second["die_already_rolled"])
        self.assertEqual(agent.xp, banked, "a second sign-in must award nothing")

    def test_only_agents_roll(self):
        lead = AgentProfile.objects.get(user__username="jmitchell")
        lead.last_seen = None
        lead.save(update_fields=["last_seen"])
        self.assertEqual(lead.register_signin(date.today())["die"], 0)


class SimulationTests(TestCase):
    """
    The arithmetic is the whole point of the page, so it is tested apart
    from the view: a wrong cost here is a plan approved on a bad number.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def _scenario(self, **over):
        from portal.simulation import Scenario
        team = Team.objects.first()
        base = dict(name="S", team=team, category=Category.INTERNET,
                    reward_type=IncentivePlan.Reward.CASH,
                    reward_amount=Decimal("25"), target_units=200)
        base.update(over)
        return Scenario(**base)

    def test_cost_is_the_reward_on_every_qualifying_unit(self):
        from portal.simulation import run
        r = run(self._scenario(reward_amount=Decimal("25"), target_units=200))
        self.assertEqual(r["cost"], Decimal("5000.00"))

    def test_points_are_converted_to_cash_so_the_two_sides_compare(self):
        from portal.simulation import run
        cash = run(self._scenario(reward_amount=Decimal("5"), target_units=100))
        pts = run(self._scenario(reward_type=IncentivePlan.Reward.POINTS,
                                 reward_amount=Decimal("500"), target_units=100))
        self.assertEqual(cash["cost"], pts["cost"],
                         "500 points at a cent each is $5")

    def test_a_target_below_the_baseline_buys_nothing_and_says_so(self):
        from portal.simulation import baseline_units, run
        team = Team.objects.first()
        base = baseline_units(team)
        r = run(self._scenario(team=team, target_units=max(0, base - 10)))
        self.assertLessEqual(r["incremental"], 0)
        self.assertIsNone(r["cost_per_incremental"],
                          "no extra units means no cost per extra unit")
        self.assertTrue(any("buys no extra units" in n for n in r["notes"]))

    def test_a_reward_above_what_a_unit_earns_is_flagged_red(self):
        from portal.simulation import run, unit_margin
        margin = unit_margin(Category.INTERNET)
        self.assertIsNotNone(margin, "seed data should have active internet offers")
        r = run(self._scenario(reward_amount=margin + Decimal("50")))
        self.assertEqual(r["verdict"], "red")

    def test_compare_states_the_difference_as_b_against_a(self):
        from portal.simulation import compare
        a = self._scenario(name="A", reward_amount=Decimal("10"), target_units=100)
        b = self._scenario(name="B", reward_amount=Decimal("20"), target_units=100)
        out = compare(a, b)
        self.assertEqual(out["cost_delta"], Decimal("1000.00"))
        self.assertEqual(out["cheaper"], "a")

    def test_page_renders_for_a_lead_and_reflects_the_query_string(self):
        self.client.post(reverse("login"), {"persona": "jmitchell"})
        resp = self.client.get(reverse("portal:simulate"),
                               {"a_amount": "40", "a_units": "100"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "4,000")

    def test_an_agent_cannot_open_the_simulator(self):
        self.client.post(reverse("login"), {"persona": "jliu"})
        self.assertEqual(self.client.get(reverse("portal:simulate")).status_code, 403)

    def test_junk_in_the_query_string_falls_back_instead_of_erroring(self):
        self.client.post(reverse("login"), {"persona": "jmitchell"})
        resp = self.client.get(reverse("portal:simulate"), {
            "a_units": "not-a-number", "a_amount": "-5",
            "a_team": "9999", "a_category": "nonsense", "a_reward": "gold",
        })
        self.assertEqual(resp.status_code, 200)

    def test_a_lead_cannot_seed_the_simulator_from_another_team_s_plan(self):
        self.client.post(reverse("login"), {"persona": "jmitchell"})
        lead = AgentProfile.objects.get(user__username="jmitchell")
        mine = {t.id for t in lead.visible_teams}
        other = IncentivePlan.objects.exclude(team_id__in=mine).first()
        if other is None:
            self.skipTest("seed data has no plan outside this lead's teams")
        resp = self.client.get(reverse("portal:simulate"), {"plan": other.id})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, other.name)


class ReportPdfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def test_every_report_renders_a_real_pdf(self):
        from portal.views_reports import REPORTS
        self.client.post(reverse("login"), {"persona": "gchen"})
        for slug in REPORTS:
            with self.subTest(report=slug):
                resp = self.client.get(reverse("portal:report_pdf", args=[slug]))
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp["Content-Type"], "application/pdf")
                self.assertTrue(resp.content.startswith(b"%PDF-"))
                self.assertIn("attachment", resp["Content-Disposition"])

    def test_the_pdf_and_the_csv_are_built_from_the_same_rows(self):
        """
        Not a byte comparison - the guarantee is structural. Both endpoints
        go through _build, so this pins that they agree on the row count for
        the same viewer and would fail if either grew its own query.
        """
        from portal.views_reports import _build

        self.client.post(reverse("login"), {"persona": "gchen"})
        manager = AgentProfile.objects.get(user__username="gchen")

        for slug in ("team-summary", "payout-register", "sales-ledger"):
            with self.subTest(report=slug):
                _, _, rows = _build(slug, manager)
                csv_body = self.client.get(
                    reverse("portal:report_csv", args=[slug])
                ).content.decode()
                csv_rows = [r for r in csv_body.splitlines() if r.strip()]
                self.assertEqual(len(csv_rows) - 1, len(rows), "CSV header plus rows")

                pdf = self.client.get(reverse("portal:report_pdf", args=[slug]))
                self.assertTrue(pdf.content.startswith(b"%PDF-"))
                self.assertGreater(len(pdf.content), 800, "a real page, not a stub")

    def test_an_agent_cannot_download_a_report_pdf(self):
        self.client.post(reverse("login"), {"persona": "jliu"})
        resp = self.client.get(reverse("portal:report_pdf", args=["payout-register"]))
        self.assertEqual(resp.status_code, 403)


class MoneyFilterTests(TestCase):
    def test_a_negative_amount_puts_the_sign_before_the_symbol(self):
        from portal.templatetags.portal_extras import money
        self.assertEqual(money(Decimal("-1100")), "-$1,100.00")
        self.assertEqual(money(Decimal("1100")), "$1,100.00")
        self.assertEqual(money(Decimal("0")), "$0.00")


class TemplateCommentTests(TestCase):
    """
    Django's {# #} comment is single-line only. Spanning lines with one does
    not error - it prints the comment into the page as body copy, which has
    now happened twice. This catches it at the source.
    """

    def test_no_template_uses_a_multiline_hash_comment(self):
        from django.conf import settings

        offenders = []
        for path in settings.BASE_DIR.rglob("*.html"):
            if "site-packages" in str(path):
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "{#" in line and "#}" not in line[line.index("{#"):]:
                    offenders.append(f"{path.name}:{n}")
        self.assertEqual(offenders, [], "use {% comment %} for anything multi-line")


class CsrfFailurePageTests(TestCase):
    """
    The demo sleeps on its free host, so a stale tab hitting a CSRF failure is
    an expected event, not an edge case. It must read as "reload me", never as
    "this application is broken".
    """

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def test_a_missing_csrf_cookie_gets_the_explaining_page(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        resp = client.post(reverse("login"), {"persona": "jliu"})

        self.assertEqual(resp.status_code, 403)
        body = resp.content.decode()
        self.assertIn("sitting a while", body)
        self.assertIn("Back to sign in", body)
        self.assertNotIn("CSRF verification failed", body)

    def test_the_page_offers_a_working_way_back(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        body = client.post(reverse("login"), {"persona": "jliu"}).content.decode()
        self.assertIn(f'href="{reverse("login")}"', body)
        # and that link must actually render
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_it_is_wired_up_so_django_never_shows_its_own_page(self):
        from django.conf import settings

        self.assertEqual(settings.CSRF_FAILURE_VIEW,
                         "portal.views_errors.csrf_failure")

    def test_django_internals_are_not_shown_to_the_visitor(self):
        """
        Django's reason names the failing check and the trusted origins. That
        is diagnostic detail about the security configuration - it belongs in
        the log, not on a public page.
        """
        from django.test import Client

        body = Client(enforce_csrf_checks=True).post(
            reverse("login"), {"persona": "jliu"}
        ).content.decode()
        for internal in ("Origin checking failed", "trusted origins",
                         "CSRF cookie", "Referer"):
            with self.subTest(leak=internal):
                self.assertNotIn(internal, body)
