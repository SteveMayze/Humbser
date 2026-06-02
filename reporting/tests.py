from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .services import build_report_draft


class DashboardViewTests(TestCase):
    def test_dashboard_page_loads(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Year-end rental reporting draft")

    def test_dashboard_calculates_shortfall_and_rent_increase(self):
        response = self.client.post(
            reverse("dashboard"),
            {
                "property_name": "River Cottage",
                "tenant_name": "Alex Tenant",
                "report_year": 2025,
                "utility_costs": "2500.00",
                "tenant_contributions": "2000.00",
                "current_weekly_rent": "600.00",
                "proposed_increase_percent": "4.50",
                "increase_reason": "Council guidance and rising utilities",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "$500.00")
        self.assertContains(response, "$627.00")
        self.assertContains(response, "Council guidance and rising utilities")


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
