from django.db import models


class Property(models.Model):
    name = models.CharField(max_length=200)
    street_address = models.CharField(max_length=255)
    suburb = models.CharField(max_length=120, blank=True)
    council_area = models.CharField(max_length=120, blank=True)
    utilities_recovered_via_rent = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Tenant(models.Model):
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="tenants",
    )
    full_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    tenancy_start = models.DateField()
    tenancy_end = models.DateField(blank=True, null=True)
    weekly_rent = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class ReportingRun(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready for review"
        SENT = "sent", "Sent to tenant"

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="reporting_runs",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="reporting_runs",
    )
    report_year = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    utility_costs = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tenant_contributions = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    council_increase_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    proposed_weekly_rent = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shortfall_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-report_year", "property__name"]
        unique_together = ("tenant", "report_year")

    def __str__(self):
        return f"{self.property} report for {self.report_year}"


class SourceDocument(models.Model):
    class DocumentType(models.TextChoices):
        BANK_STATEMENT = "bank_statement", "Bank statement PDF"
        PROPERTY_MANAGER = "property_manager", "Property manager statement"
        COUNCIL_REPORT = "council_report", "Council rental report"
        OTHER = "other", "Other"

    class ProcessingState(models.TextChoices):
        PENDING = "pending", "Pending"
        IMPORTED = "imported", "Imported"
        REVIEWED = "reviewed", "Reviewed"

    reporting_run = models.ForeignKey(
        ReportingRun,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    document_type = models.CharField(max_length=30, choices=DocumentType.choices)
    reference = models.CharField(
        max_length=255,
        help_text="Path, filename or note describing where the source document came from.",
    )
    parser_hint = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional parser name, such as pdf2csv, for later ingestion work.",
    )
    processing_state = models.CharField(
        max_length=20,
        choices=ProcessingState.choices,
        default=ProcessingState.PENDING,
    )
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-imported_at"]

    def __str__(self):
        return f"{self.get_document_type_display()} ({self.reference})"
