from django.contrib import admin

from .models import BankTransaction, Property, ReportingRun, SourceDocument, StatementPattern, Tenant, WEGReport


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "owner_name", "suburb", "council_area", "utilities_recovered_via_rent")
    search_fields = ("name", "street_address", "suburb", "owner_name", "owner_address", "owner_city", "council_area")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("full_name", "property", "weekly_rent", "tenancy_start", "tenancy_end")
    list_filter = ("property",)
    search_fields = ("full_name", "email")


@admin.register(ReportingRun)
class ReportingRunAdmin(admin.ModelAdmin):
    list_display = (
        "property",
        "tenant",
        "report_year",
        "status",
        "shortfall_amount",
        "proposed_weekly_rent",
    )
    list_filter = ("status", "report_year")
    search_fields = ("property__name", "tenant__full_name")


@admin.register(SourceDocument)
class SourceDocumentAdmin(admin.ModelAdmin):
    list_display = ("document_type", "reference", "processing_state", "imported_at")
    list_filter = ("document_type", "processing_state")


@admin.register(StatementPattern)
class StatementPatternAdmin(admin.ModelAdmin):
    list_display = ("regex", "classification", "created_at")
    list_filter = ("classification",)
    search_fields = ("regex",)


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_date", "detail", "amount", "classification", "source_document")
    list_filter = ("classification", "transaction_date")
    search_fields = ("detail",)
    date_hierarchy = "transaction_date"


@admin.register(WEGReport)
class WEGReportAdmin(admin.ModelAdmin):
    list_display = (
        "report_year",
        "property_management",
        "heating",
        "hot_water",
        "service_costs",
        "co2",
        "land_tax",
    )
