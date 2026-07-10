from django.db import models


class Property(models.Model):
    name = models.CharField(max_length=200)
    street_address = models.CharField(max_length=255)
    suburb = models.CharField(max_length=120, blank=True)
    owner_name = models.CharField(max_length=200, blank=True)
    owner_address = models.CharField(max_length=255, blank=True)
    owner_city = models.CharField(max_length=120, blank=True)
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
        UTILITY_STATEMENT = "utility_statement", "Utility statement"
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
        null=True,
        blank=True,
    )
    document_type = models.CharField(max_length=30, choices=DocumentType.choices)
    uploaded_file = models.FileField(
        upload_to="source_documents/",
        null=True,
        blank=True,
    )
    reference = models.CharField(
        max_length=255,
        blank=True,
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
        return f"{self.get_document_type_display()} ({self.reference or self.uploaded_file})"


class StatementPattern(models.Model):
    """
    A regex pattern used to match description entries when parsing bank statement PDFs.
    Each pattern carries a classification that groups the matched line's purpose.
    """

    class Classification(models.TextChoices):
        TENANT_RENT = "tenant_rent", "Tenant — Rent"
        TENANT_OPERATING = "tenant_operating", "Tenant — Operating advance"
        TENANT_HEATING = "tenant_heating", "Tenant — Heating advance"
        TENANT_SHORTFALL = "tenant_shortfall", "Tenant — Shortfall payment"
        MANAGEMENT = "management", "Management"
        LAND_TAX = "land_tax", "Land tax"
        AFFILIATIONS = "affiliations", "Affiliations"

    regex = models.CharField(
        max_length=255,
        unique=True,
        help_text="Python-compatible regular expression matched against the transaction description.",
    )
    classification = models.CharField(
        max_length=30,
        choices=Classification.choices,
        default=Classification.TENANT_RENT,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["classification", "regex"]

    def __str__(self):
        return f"{self.get_classification_display()}: {self.regex}"


class WEGReport(models.Model):
    """
    Manually entered transferable cost figures from the property manager's WEG report.
    One record per reporting year.
    """
    report_year = models.PositiveIntegerField(unique=True)
    property_management = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    heating = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    hot_water = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    service_costs = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    co2 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    land_tax = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="From the separate council land tax statement.",
    )
    prior_year_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Optional prior-year Nebenkosten balance carried into this year's invoice.",
    )
    # Monthly rent breakdown per the tenancy agreement
    monthly_rent = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Monthly Kaltmiete per tenancy agreement.",
    )
    monthly_heating_advance = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Monthly Heizkostenvorschuss per tenancy agreement.",
    )
    monthly_operating_advance = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Monthly Betriebskosten Vorauszahlung per tenancy agreement.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-report_year"]

    def __str__(self):
        return f"WEG Report {self.report_year}"

    @property
    def heating_costs_total(self):
        """Delta-t total: heating + hot water + CO2 + service costs."""
        return self.heating + self.hot_water + self.service_costs + self.co2

    @property
    def net_hausverwaltung(self):
        """True admin fee: the gross property_management figure minus embedded Delta-t costs."""
        return self.property_management - self.heating_costs_total

    @property
    def operating_costs_total(self):
        """Umlagefähige Betriebskosten: net Hausverwaltung + Grundsteuer."""
        return self.net_hausverwaltung + self.land_tax

    @property
    def total_transferable(self):
        """= property_management + land_tax (delta-t cancels out)."""
        return self.property_management + self.land_tax

    @property
    def annual_rent(self):
        return self.monthly_rent * 12

    @property
    def annual_heating_advance(self):
        return self.monthly_heating_advance * 12

    @property
    def annual_operating_advance(self):
        return self.monthly_operating_advance * 12


class RentIncreasePlan(models.Model):
    """Persisted planning inputs for a future rent increase proposal."""

    report_year = models.PositiveIntegerField(unique=True)
    current_weekly_cold_rent = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    projected_annual_maintenance_costs = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    projected_annual_utility_costs = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    mietspiegel_weekly_cold_rent = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    base_increase_percent = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-report_year"]

    def __str__(self):
        return f"Rent Increase Plan {self.report_year}"

    @property
    def projected_annual_total_costs(self):
        return self.projected_annual_maintenance_costs + self.projected_annual_utility_costs


class BankTransaction(models.Model):
    """
    A single transaction line extracted from a parsed bank statement PDF.
    Classified by matching against stored StatementPattern regexes.
    """

    source_document = models.ForeignKey(
        SourceDocument,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    transaction_date = models.DateField()
    detail = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    classification = models.CharField(
        max_length=30,
        choices=StatementPattern.Classification.choices,
        blank=True,
        default="",
    )
    matched_pattern = models.ForeignKey(
        StatementPattern,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transactions",
    )

    class Meta:
        ordering = ["transaction_date"]

    def __str__(self):
        return f"{self.transaction_date} | {self.detail[:60]} | {self.amount}"
