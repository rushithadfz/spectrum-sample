from django.urls import path

from . import (
    views,
    views_incentive as inc,
    views_plans as plans,
    views_close as close_v,
    views_admin as admin_v,
    views_directory as dir_v,
    views_reports as reports_v,
    views_sales as sales_v,
    views_simulate as sim_v,
    views_spend as spend,
    views_team as team,
)

app_name = "portal"

urlpatterns = [
    # --- incentive portal (matches the reference POC) ---
    path("", inc.home, name="dashboard"),
    path("home/", inc.home, name="home"),
    path("incentives/feed/", inc.incentive_feed, name="incentive_feed"),
    path("incentives/detail/", inc.incentive_detail, name="incentive_detail"),
    path("incentives/detail/<str:code>/", inc.incentive_detail, name="incentive_detail_code"),
    path("incentives/calculator/", inc.calculator, name="calculator"),
    path("disputes/", inc.disputes, name="disputes"),
    path("sales/", sales_v.sales, name="sales"),
    path("close/", close_v.close, name="close"),
    path("agents/", dir_v.directory, name="directory"),
    path("channels/", admin_v.channels, name="channels"),
    path("settings/", admin_v.settings, name="settings"),
    path("reports/", reports_v.reports, name="reports"),
    path("reports/<slug:slug>/", reports_v.report_detail, name="report_detail"),
    path("reports/<slug:slug>.csv", reports_v.report_csv, name="report_csv"),
    path("reports/<slug:slug>.pdf", reports_v.report_pdf, name="report_pdf"),
    path("quests/<int:quest_id>/claim/", inc.claim_quest, name="claim_quest"),

    # --- hierarchy: team lead and manager ---
    path("team/", team.team_view, name="team"),
    path("market/", team.market_view, name="market"),
    path("spend/", spend.spend, name="spend"),

    # --- market intelligence, plan builder, approvals ---
    path("trends/", plans.trends, name="trends"),
    path("plans/", plans.plan_list, name="plans"),
    path("plans/new/", plans.plan_new, name="plan_new"),
    path("plans/<int:plan_id>/edit/", plans.plan_new, name="plan_edit"),
    path("plans/<int:plan_id>/submit/", plans.plan_submit, name="plan_submit"),
    path("plans/<int:plan_id>/decide/", plans.plan_decide, name="plan_decide"),
    path("plans/<int:plan_id>/clone/", plans.plan_clone, name="plan_clone"),
    path("simulate/", sim_v.simulate, name="simulate"),

    # --- assistant ---
    path("ask/", plans.ask, name="ask"),
    path("ask/api/", plans.ask_api, name="ask_api"),

    # --- product catalog ---
    path("products/", views.product_list, name="products"),
    path("products/<slug:slug>/", views.product_detail, name="product_detail"),
]
