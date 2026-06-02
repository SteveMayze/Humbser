from django.contrib import admin

from .models import Property, ReportingRun, SourceDocument, Tenant


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "suburb", "council_area", "utilities_recovered_via_rent")
    search_fields = ("name", "street_address", "suburb", "council_area")


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
    list_display = ("reporting_run", "document_type", "reference", "processing_state", "parser_hint")
    list_filter = ("document_type", "processing_state")
    search_fields = ("reference", "parser_hint")
