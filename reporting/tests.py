import datetime
from io import BytesIO
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from .models import BankTransaction, Property, SourceDocument, StatementPattern, Tenant, WEGReport
from .services import build_annual_settlement, build_report_draft


class SettlementFixtureMixin:
    def create_weg_report(self, report_year=2025, **overrides):
        defaults = {
            "report_year": report_year,
            "property_management": Decimal("3697.25"),
            "heating": Decimal("1097.68"),
            "hot_water": Decimal("596.73"),
            "service_costs": Decimal("298.59"),
            "co2": Decimal("0.00"),
            "land_tax": Decimal("350.54"),
            "monthly_rent": Decimal("490.00"),
            "monthly_heating_advance": Decimal("125.00"),
            "monthly_operating_advance": Decimal("175.00"),
            "prior_year_balance": Decimal("0.00"),
        }
        defaults.update(overrides)
        return WEGReport.objects.create(
            **defaults,
        )

    def create_tx(self, tx_date, amount, classification, detail=None):
        doc = SourceDocument.objects.create(
            document_type=SourceDocument.DocumentType.BANK_STATEMENT,
            reference=f"stmt-{tx_date.isoformat()}.pdf",
        )
        return BankTransaction.objects.create(
            source_document=doc,
            transaction_date=tx_date,
            detail=detail or f"Payment {tx_date.isoformat()}",
            amount=Decimal(amount),
            classification=classification,
        )

    def create_property_and_tenant(self):
        property_obj = Property.objects.create(
            name="Humbser Strasse 12a",
            street_address="Humbser Strasse 12a",
            suburb="90763 Fürth",
            owner_name="Heidi & Steve Mayze",
            owner_address="Gutenbergstrasse 2b",
            owner_city="91058 Erlangen-Bruck",
        )
        tenant = Tenant.objects.create(
            property=property_obj,
            full_name="Bahar Konci",
            tenancy_start=datetime.date(2024, 1, 1),
            weekly_rent=Decimal("0.00"),
        )
        return property_obj, tenant


class DashboardViewTests(SettlementFixtureMixin, TestCase):
    def test_dashboard_page_loads(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nebenkosten Abrechnung")

    def test_dashboard_renders_annual_settlement_for_selected_year(self):
        self.create_weg_report(2025)
        self.create_tx(datetime.date(2025, 6, 10), "9480.00", StatementPattern.Classification.TENANT_RENT)

        response = self.client.get(reverse("dashboard"), {"year": 2025})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "5880.00")
        self.assertContains(response, "447.79")


class ReportDraftServiceTests(TestCase):
    def test_build_report_draft_never_returns_negative_shortfall(self):
        draft = build_report_draft(
            {
                "property_name": "River Cottage",
                "tenant_name": "Alex Tenant",
                "report_year": 2025,
                "utility_costs": Decimal("1200.00"),
                "tenant_contributions": Decimal("1500.00"),
                "current_weekly_rent": Decimal("600.00"),
                "proposed_increase_percent": Decimal("3.00"),
                "increase_reason": "Council guidance",
            }
        )

        self.assertEqual(draft.utility_shortfall, Decimal("0.00"))
        self.assertEqual(draft.proposed_weekly_rent, Decimal("618.00"))


class ReportingWindowTests(SettlementFixtureMixin, TestCase):
    def test_dashboard_uses_december_and_january_reporting_window(self):
        C = StatementPattern.Classification
        # Included for report year 2025
        self.create_tx(datetime.date(2024, 12, 10), "100.00", C.TENANT_RENT)
        self.create_tx(datetime.date(2025, 6, 10), "200.00", C.TENANT_RENT)
        self.create_tx(datetime.date(2026, 1, 10), "300.00", C.TENANT_RENT)

        # Excluded from report year 2025
        self.create_tx(datetime.date(2024, 11, 30), "999.00", C.TENANT_RENT)
        self.create_tx(datetime.date(2026, 2, 1), "999.00", C.TENANT_RENT)

        settlement = build_annual_settlement(2025)

        self.assertEqual(settlement.rent_income, Decimal("600.00"))

    def test_upload_page_lists_transactions_in_reporting_window(self):
        C = StatementPattern.Classification
        included = self.create_tx(datetime.date(2024, 12, 20), "120.00", C.TENANT_OPERATING)
        self.create_tx(datetime.date(2026, 1, 5), "80.00", C.TENANT_HEATING)
        excluded = self.create_tx(datetime.date(2024, 11, 20), "50.00", C.TENANT_OPERATING)

        response = self.client.get(reverse("upload_documents"), {"year": 2025})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, included.detail)
        self.assertNotContains(response, excluded.detail)
        self.assertContains(response, "01.12.2024")
        self.assertContains(response, "31.01.2026")


class UploadConfigurationTests(SettlementFixtureMixin, TestCase):
    def test_upload_page_saves_invoice_details_without_admin(self):
        self.create_weg_report(2025)

        response = self.client.post(
            reverse("upload_documents"),
            {
                "report_year": 2025,
                "property_management": "3697.25",
                "heating": "1097.68",
                "hot_water": "596.73",
                "service_costs": "298.59",
                "co2": "0.00",
                "land_tax": "350.54",
                "prior_year_balance": "447.79",
                "monthly_rent": "490.00",
                "monthly_heating_advance": "125.00",
                "monthly_operating_advance": "175.00",
                "owner_name": "Heidi & Steve Mayze",
                "owner_address": "Gutenbergstrasse 2b",
                "owner_city": "91058 Erlangen-Bruck",
                "property_name": "Humbser Strasse 12a",
                "property_street_address": "Humbser Strasse 12a",
                "property_city": "90763 Fürth",
                "tenant_name": "Bahar Konci",
            },
        )

        self.assertEqual(response.status_code, 200)
        property_obj = Property.objects.get(name="Humbser Strasse 12a")
        tenant = Tenant.objects.get(property=property_obj)
        weg = WEGReport.objects.get(report_year=2025)
        self.assertEqual(property_obj.owner_name, "Heidi & Steve Mayze")
        self.assertEqual(tenant.full_name, "Bahar Konci")
        self.assertEqual(weg.prior_year_balance, Decimal("447.79"))
        self.assertContains(response, "Invoice details for 2025 saved.")


class InvoicePdfTests(SettlementFixtureMixin, TestCase):
    def test_invoice_pdf_renders_single_page_report(self):
        self.create_property_and_tenant()
        self.create_weg_report(2025)
        self.create_tx(datetime.date(2025, 6, 10), "9480.00", StatementPattern.Classification.TENANT_RENT, detail="Annual bundled payment")

        response = self.client.get(reverse("download_invoice_pdf"), {"year": 2025})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        reader = PdfReader(BytesIO(response.content))
        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        self.assertIn("Nebenkosten 2025", text)
        self.assertIn("01.01.2025 - 31.12.2025", text)
        self.assertIn("Heidi & Steve Mayze", text)
        self.assertIn("Bahar Konci", text)
        self.assertIn("447,79", text)

    def test_invoice_pdf_requires_property_and_tenant_configuration(self):
        response = self.client.get(reverse("download_invoice_pdf"), {"year": 2025})

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "No active tenant is configured", status_code=400)

    def test_invoice_pdf_uses_explicit_prior_year_balance_when_configured(self):
        self.create_property_and_tenant()
        self.create_weg_report(2025, prior_year_balance=Decimal("447.79"))
        self.create_tx(datetime.date(2025, 6, 10), "9480.00", StatementPattern.Classification.TENANT_RENT)
        self.create_tx(datetime.date(2026, 1, 5), "447.79", StatementPattern.Classification.TENANT_OPERATING)

        response = self.client.get(reverse("download_invoice_pdf"), {"year": 2025})

        self.assertEqual(response.status_code, 200)
        text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("Nebenkosten 2024", text)
        self.assertIn("Zahlung Nebenkosten 2024", text)
        self.assertIn("447,79", text)
