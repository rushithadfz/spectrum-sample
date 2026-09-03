from django.contrib import admin

from .models import (
    AgentProfile,
    Announcement,
    Cutoff,
    Highlight,
    Incentive,
    Offer,
    PerformanceSnapshot,
    Persona,
    Product,
    ProductLink,
    Quota,
    Resource,
    Sale,
    Spec,
    SpecGroup,
    SupportContact,
)


class HighlightInline(admin.TabularInline):
    model = Highlight
    extra = 1


class ProductLinkInline(admin.TabularInline):
    model = ProductLink
    extra = 1


class SpecInline(admin.TabularInline):
    model = Spec
    extra = 3


class SpecGroupInline(admin.TabularInline):
    model = SpecGroup
    extra = 1
    show_change_link = True


class QuotaInline(admin.TabularInline):
    model = Quota
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "category", "price_note", "order")
    list_filter = ("category",)
    search_fields = ("name", "sku", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [HighlightInline, SpecGroupInline, ProductLinkInline]


@admin.register(SpecGroup)
class SpecGroupAdmin(admin.ModelAdmin):
    list_display = ("product", "name", "order")
    list_filter = ("product",)
    inlines = [SpecInline]


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "status", "price", "commission", "spiff")
    list_filter = ("category", "status")
    search_fields = ("name", "code", "blurb")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("products",)


@admin.register(Incentive)
class IncentiveAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "status", "payout", "progress", "goal", "earned")
    list_filter = ("kind", "status")
    search_fields = ("name", "description")
    filter_horizontal = ("offers",)


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("agent_id", "full_name", "role", "market", "team", "tier")
    search_fields = ("agent_id", "user__username", "user__first_name", "user__last_name")
    inlines = [QuotaInline]


@admin.register(PerformanceSnapshot)
class PerformanceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("agent", "period", "is_current", "units_sold", "gross_commission", "spiff_earned")
    list_filter = ("is_current",)


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("order_no", "sold_on", "customer", "offer", "units", "base", "spiff", "status")
    list_filter = ("status", "sold_on")
    search_fields = ("order_no", "customer")
    date_hierarchy = "sold_on"


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("posted_on", "tag", "tone", "text")
    list_filter = ("tag", "tone")


@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ("name", "title", "slug", "is_available", "user", "order")
    list_filter = ("is_available",)
    prepopulated_fields = {"slug": ("name",)}


admin.site.register([Resource, SupportContact, Cutoff])

admin.site.site_header = "Agent Portal administration"
admin.site.site_title = "Agent Portal"
admin.site.index_title = "Catalog, offers and incentives"
