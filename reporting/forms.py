import datetime
from decimal import Decimal

from django import forms
from django.db.models import Q


class YearEndReportDraftForm(forms.Form):
    property_name = forms.CharField(max_length=200)
    tenant_name = forms.CharField(max_length=200)
    report_year = forms.IntegerField(min_value=2000)
    utility_costs = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10)
    tenant_contributions = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10)
    current_weekly_rent = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10)
    proposed_increase_percent = forms.DecimalField(
        min_value=0,
        decimal_places=2,
        max_digits=5,
        help_text="Use the council rental report or your own review figure.",
    )
    increase_reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        initial="Annual council rental guidance and verified utility costs.",
    )


class RentIncreasePlanningForm(forms.Form):
    report_year = forms.IntegerField(widget=forms.HiddenInput())
    current_weekly_cold_rent = forms.DecimalField(
        min_value=0,
        decimal_places=2,
        max_digits=10,
        required=True,
        label="Current weekly cold rent",
        help_text="Enter the current weekly cold rent for the year the increase will be based on.",
    )
    projected_annual_maintenance_costs = forms.DecimalField(
        min_value=0,
        decimal_places=2,
        max_digits=10,
        required=False,
        initial=0,
        label="Projected annual maintenance costs",
        help_text="Projected WEG costs for maintenance and building management.",
    )
    projected_annual_utility_costs = forms.DecimalField(
        min_value=0,
        decimal_places=2,
        max_digits=10,
        required=False,
        initial=0,
        label="Projected annual utility costs",
        help_text="Projected heating, warm water and related utility costs.",
    )
    mietspiegel_weekly_cold_rent = forms.DecimalField(
        min_value=0,
        decimal_places=2,
        max_digits=10,
        label="Mietspiegel weekly cold rent",
        help_text="Enter the benchmark cold rent from the Mietspiegel calculation.",
    )
    base_increase_percent = forms.DecimalField(
        min_value=0,
        max_value=5,
        decimal_places=2,
        max_digits=5,
        required=False,
        initial=5,
        label="Base increase percent",
        help_text="The planning uplift should not exceed 5%.",
    )

    def _decimal_or_zero(self, field_name):
        return self.cleaned_data.get(field_name) or 0

    def save_or_update(self):
        from .models import RentIncreasePlan

        year = self.cleaned_data["report_year"]
        obj, _ = RentIncreasePlan.objects.update_or_create(
            report_year=year,
            defaults={
                "current_weekly_cold_rent": self._decimal_or_zero("current_weekly_cold_rent"),
                "projected_annual_maintenance_costs": self._decimal_or_zero("projected_annual_maintenance_costs"),
                "projected_annual_utility_costs": self._decimal_or_zero("projected_annual_utility_costs"),
                "mietspiegel_weekly_cold_rent": self._decimal_or_zero("mietspiegel_weekly_cold_rent"),
                "base_increase_percent": self._decimal_or_zero("base_increase_percent"),
            },
        )
        return obj


class BankStatementUploadForm(forms.Form):
    bank_statements = forms.FileField(
        required=False,
        label="Bank statements",
        help_text="Select or drag up to 12 monthly PDF statements.",
    )


class WEGReportForm(forms.Form):
    report_year = forms.IntegerField(
        widget=forms.HiddenInput(),
        initial=datetime.date.today().year,
    )
    property_management = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="Hausverwaltung (gross)",
        help_text="The single gross figure from the WEG report \u2014 includes the Delta-t costs.",
    )
    heating = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="Heating",
    )
    hot_water = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="Hot water",
    )
    service_costs = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="Service Costs",
    )
    co2 = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="CO2",
    )
    land_tax = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="Land Tax",
        help_text="From the separate council land tax statement.",
    )
    prior_year_balance = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="Prior-year Nebenkosten balance",
        help_text="Optional carry-over amount to show in the invoice when a prior-year report is not stored yet.",
    )
    monthly_rent = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="Kaltmiete",
        help_text="Monthly rent component per tenancy agreement.",
    )
    monthly_heating_advance = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="Heizkostenvorschuss",
        help_text="Monthly warm/heating advance per tenancy agreement.",
    )
    monthly_operating_advance = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=10,
        required=False, initial=0, label="Betriebskosten Vorauszahlung",
        help_text="Monthly operating costs advance per tenancy agreement.",
    )

    def _decimal_or_zero(self, field_name):
        return self.cleaned_data.get(field_name) or 0

    def save_or_update(self):
        from .models import WEGReport
        year = self.cleaned_data["report_year"]
        obj, _ = WEGReport.objects.update_or_create(
            report_year=year,
            defaults={
                "property_management": self._decimal_or_zero("property_management"),
                "heating": self._decimal_or_zero("heating"),
                "hot_water": self._decimal_or_zero("hot_water"),
                "service_costs": self._decimal_or_zero("service_costs"),
                "co2": self._decimal_or_zero("co2"),
                "land_tax": self._decimal_or_zero("land_tax"),
                "prior_year_balance": self._decimal_or_zero("prior_year_balance"),
                "monthly_rent": self._decimal_or_zero("monthly_rent"),
                "monthly_heating_advance": self._decimal_or_zero("monthly_heating_advance"),
                "monthly_operating_advance": self._decimal_or_zero("monthly_operating_advance"),
            },
        )
        return obj


class InvoiceSettingsForm(forms.Form):
    report_year = forms.IntegerField(
        widget=forms.HiddenInput(),
        initial=datetime.date.today().year,
    )
    owner_name = forms.CharField(max_length=200, label="Owner name")
    owner_address = forms.CharField(max_length=255, label="Owner street address")
    owner_city = forms.CharField(max_length=120, label="Owner postcode and city")
    property_name = forms.CharField(max_length=200, label="Property name")
    property_street_address = forms.CharField(max_length=255, label="Rental property street address")
    property_city = forms.CharField(max_length=120, label="Rental property postcode and city")
    tenant_name = forms.CharField(max_length=200, label="Tenant name")

    def save_or_update(self):
        from .models import Property, Tenant

        year = self.cleaned_data["report_year"]
        period_start = datetime.date(year, 1, 1)
        period_end = datetime.date(year, 12, 31)

        tenant = (
            Tenant.objects.select_related("property")
            .filter(tenancy_start__lte=period_end)
            .filter(Q(tenancy_end__isnull=True) | Q(tenancy_end__gte=period_start))
            .order_by("tenancy_start", "pk")
            .first()
        )

        if tenant is not None:
            property_obj = tenant.property
        else:
            property_obj = Property.objects.order_by("pk").first() or Property()

        property_obj.name = self.cleaned_data["property_name"]
        property_obj.street_address = self.cleaned_data["property_street_address"]
        property_obj.suburb = self.cleaned_data["property_city"]
        property_obj.owner_name = self.cleaned_data["owner_name"]
        property_obj.owner_address = self.cleaned_data["owner_address"]
        property_obj.owner_city = self.cleaned_data["owner_city"]
        property_obj.save()

        if tenant is None:
            tenant = Tenant(
                property=property_obj,
                tenancy_start=period_start,
                weekly_rent=Decimal("0.00"),
            )

        tenant.property = property_obj
        tenant.full_name = self.cleaned_data["tenant_name"]
        if not tenant.tenancy_start:
            tenant.tenancy_start = period_start
        if tenant.weekly_rent is None:
            tenant.weekly_rent = Decimal("0.00")
        tenant.save()
        return tenant
