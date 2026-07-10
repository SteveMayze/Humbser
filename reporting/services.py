from dataclasses import dataclass
import datetime
from io import BytesIO
import re
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


TWOPLACES = Decimal("0.01")
FIVE_EURO_INCREMENT = Decimal("5.00")


def to_money(value):
    return Decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def round_up_to_increment(value: Decimal, increment: Decimal = FIVE_EURO_INCREMENT) -> Decimal:
    value = to_money(value)
    increment = to_money(increment)
    if increment <= 0:
        raise ValueError("Increment must be positive.")
    rounded_steps = (value / increment).to_integral_value(rounding=ROUND_CEILING)
    return to_money(rounded_steps * increment)


def resolve_current_cold_rent(tenant, report_year: int) -> Decimal:
    if tenant and tenant.weekly_rent > 0:
        return to_money(tenant.weekly_rent)

    from .models import WEGReport

    for candidate_year in (datetime.date.today().year, report_year):
        weg = WEGReport.objects.filter(report_year=candidate_year).first()
        if weg and weg.monthly_rent > 0:
            return to_money(weg.monthly_rent)

    return Decimal("0.00")


@dataclass(frozen=True)
class ReportDraft:
    property_name: str
    tenant_name: str
    report_year: int
    utility_shortfall: Decimal
    proposed_weekly_rent: Decimal
    increase_reason: str
    letter_text: str


@dataclass(frozen=True)
class RentIncreaseProposal:
    property_name: str
    tenant_name: str
    current_weekly_cold_rent: Decimal
    base_increase_percent: Decimal
    base_increase_amount: Decimal
    base_planned_weekly_rent: Decimal
    projected_annual_maintenance_costs: Decimal
    projected_annual_utility_costs: Decimal
    projected_annual_total_costs: Decimal
    projected_weekly_cost_load: Decimal
    mietspiegel_weekly_cold_rent: Decimal
    cost_based_weekly_rent: Decimal
    proposed_weekly_rent: Decimal
    weekly_increase_amount: Decimal
    weekly_increase_percent: Decimal
    limiting_factor: str
    summary_text: str


@dataclass(frozen=True)
class AnnualSettlement:
    report_year: int
    period_start: datetime.date
    period_end: datetime.date
    window_start: datetime.date
    window_end: datetime.date
    weg: object | None
    rent_income: Decimal
    operating_advance: Decimal
    heating_advance: Decimal
    direct_operating_advance: Decimal
    operating_from_rent: Decimal
    shortfall_income: Decimal
    non_recurring_shortfall_income: Decimal
    has_expected: bool
    expected_rent: Decimal
    expected_operating_advance: Decimal
    expected_heating_advance: Decimal
    rent_advance_delta: Decimal | None
    operating_advance_delta: Decimal | None
    heating_advance_delta: Decimal | None
    operating_cost: Decimal
    heating_cost: Decimal
    prior_year_balance: Decimal
    operating_delta: Decimal
    heating_delta: Decimal
    net_balance: Decimal


def build_report_draft(data):
    utility_costs = to_money(data["utility_costs"])
    tenant_contributions = to_money(data["tenant_contributions"])
    current_weekly_rent = to_money(data["current_weekly_rent"])
    proposed_increase_percent = Decimal(data["proposed_increase_percent"])

    utility_shortfall = to_money(max(Decimal("0.00"), utility_costs - tenant_contributions))
    proposed_weekly_rent = to_money(
        current_weekly_rent * (Decimal("1.00") + (proposed_increase_percent / Decimal("100")))
    )

    letter_text = (
        f"Dear {data['tenant_name']},\n\n"
        f"Our review for {data['property_name']} for {data['report_year']} shows a utility "
        f"shortfall of ${utility_shortfall:.2f}. Based on the latest council rental guidance, "
        f"the weekly rent is proposed to increase to ${proposed_weekly_rent:.2f}.\n\n"
        f"Reason for increase: {data['increase_reason']}\n\n"
        "Please review the enclosed information and contact us if you would like to discuss it."
    )

    return ReportDraft(
        property_name=data["property_name"],
        tenant_name=data["tenant_name"],
        report_year=data["report_year"],
        utility_shortfall=utility_shortfall,
        proposed_weekly_rent=proposed_weekly_rent,
        increase_reason=data["increase_reason"],
        letter_text=letter_text,
    )


def build_rent_increase_proposal(data):
    current_weekly_cold_rent = to_money(data["current_weekly_cold_rent"])
    projected_annual_maintenance_costs = to_money(data["projected_annual_maintenance_costs"])
    projected_annual_utility_costs = to_money(data["projected_annual_utility_costs"])
    mietspiegel_weekly_cold_rent = to_money(data["mietspiegel_weekly_cold_rent"])
    base_increase_percent = to_money(data.get("base_increase_percent", Decimal("5.00")))
    if base_increase_percent > Decimal("5.00"):
        base_increase_percent = Decimal("5.00")

    projected_annual_total_costs = to_money(
        projected_annual_maintenance_costs + projected_annual_utility_costs
    )
    projected_weekly_cost_load = to_money(projected_annual_total_costs / Decimal("52"))
    cost_based_weekly_rent = to_money(current_weekly_cold_rent + projected_weekly_cost_load)
    base_increase_amount = round_up_to_increment(
        (current_weekly_cold_rent * base_increase_percent) / Decimal("100"),
        Decimal("1.00"),
    )
    base_planned_weekly_rent = to_money(current_weekly_cold_rent + base_increase_amount)

    # The proposal should never reduce the current rent and should respect the 5% planning cap.
    mietspiegel_ceiling = mietspiegel_weekly_cold_rent if mietspiegel_weekly_cold_rent > current_weekly_cold_rent else None
    proposed_weekly_rent = min(base_planned_weekly_rent, cost_based_weekly_rent)
    if mietspiegel_ceiling is not None:
        proposed_weekly_rent = min(proposed_weekly_rent, mietspiegel_ceiling)
    if proposed_weekly_rent < current_weekly_cold_rent:
        proposed_weekly_rent = current_weekly_cold_rent

    weekly_increase_amount = to_money(proposed_weekly_rent - current_weekly_cold_rent)
    weekly_increase_percent = (
        to_money((weekly_increase_amount / current_weekly_cold_rent) * Decimal("100"))
        if current_weekly_cold_rent > 0
        else Decimal("0.00")
    )

    if weekly_increase_amount == 0:
        limiting_factor = "No increase required"
    elif proposed_weekly_rent == base_planned_weekly_rent:
        limiting_factor = "5% planning cap"
    elif proposed_weekly_rent == cost_based_weekly_rent:
        limiting_factor = "Projected WEG costs"
    elif mietspiegel_ceiling is not None and proposed_weekly_rent == mietspiegel_ceiling:
        limiting_factor = "Mietspiegel ceiling"
    else:
        limiting_factor = "Current rent floor"

    summary_text = (
        f"Current cold rent is {current_weekly_cold_rent:.2f} per week. "
        f"Projected WEG maintenance and utility costs total {projected_annual_total_costs:.2f} per year, "
        f"which adds {projected_weekly_cost_load:.2f} per week. "
        f"The Mietspiegel reference is {mietspiegel_weekly_cold_rent:.2f} per week, "
        f"so the proposed cold rent is {proposed_weekly_rent:.2f} per week."
    )

    return RentIncreaseProposal(
        property_name=data["property_name"],
        tenant_name=data["tenant_name"],
        current_weekly_cold_rent=current_weekly_cold_rent,
        base_increase_percent=base_increase_percent,
        base_increase_amount=base_increase_amount,
        base_planned_weekly_rent=base_planned_weekly_rent,
        projected_annual_maintenance_costs=projected_annual_maintenance_costs,
        projected_annual_utility_costs=projected_annual_utility_costs,
        projected_annual_total_costs=projected_annual_total_costs,
        projected_weekly_cost_load=projected_weekly_cost_load,
        mietspiegel_weekly_cold_rent=mietspiegel_weekly_cold_rent,
        cost_based_weekly_rent=cost_based_weekly_rent,
        proposed_weekly_rent=proposed_weekly_rent,
        weekly_increase_amount=weekly_increase_amount,
        weekly_increase_percent=weekly_increase_percent,
        limiting_factor=limiting_factor,
        summary_text=summary_text,
    )


def reporting_window_bounds(report_year: int) -> tuple[datetime.date, datetime.date]:
    return (
        datetime.date(report_year - 1, 12, 1),
        datetime.date(report_year + 1, 1, 31),
    )


def with_reporting_window(queryset, report_year: int):
    start_date, end_date = reporting_window_bounds(report_year)
    return queryset.filter(
        transaction_date__gte=start_date,
        transaction_date__lte=end_date,
    )


def get_active_tenant(report_year: int):
    from django.db.models import Q

    from .models import Tenant

    period_start = datetime.date(report_year, 1, 1)
    period_end = datetime.date(report_year, 12, 31)
    return (
        Tenant.objects.select_related("property")
        .filter(tenancy_start__lte=period_end)
        .filter(Q(tenancy_end__isnull=True) | Q(tenancy_end__gte=period_start))
        .order_by("tenancy_start", "pk")
        .first()
    )


def build_annual_settlement(report_year: int) -> AnnualSettlement:
    from django.db.models import Sum

    from .models import BankTransaction, StatementPattern, WEGReport

    weg = WEGReport.objects.filter(report_year=report_year).first()

    def tx_total(classification):
        result = (
            with_reporting_window(BankTransaction.objects, report_year)
            .filter(classification=classification)
            .aggregate(total=Sum("amount"))["total"]
        )
        return result or Decimal("0.00")

    C = StatementPattern.Classification
    zero = Decimal("0.00")

    tenant_rent_gross = tx_total(C.TENANT_RENT)
    direct_operating_advance = tx_total(C.TENANT_OPERATING)
    direct_heating_advance = tx_total(C.TENANT_HEATING)
    shortfall_income = tx_total(C.TENANT_SHORTFALL)

    has_expected = bool(
        weg and (weg.monthly_rent or weg.monthly_operating_advance or weg.monthly_heating_advance)
    )
    expected_rent = weg.annual_rent if has_expected else Decimal("0.00")
    expected_operating_advance = weg.annual_operating_advance if has_expected else Decimal("0.00")
    expected_heating_advance = weg.annual_heating_advance if has_expected else Decimal("0.00")

    operating_from_rent = zero
    heating_from_rent = zero
    if has_expected and tenant_rent_gross > zero:
        operating_from_rent = min(expected_operating_advance, tenant_rent_gross)
        remaining_rent = tenant_rent_gross - operating_from_rent
        heating_from_rent = min(expected_heating_advance, remaining_rent)

    rent_income = tenant_rent_gross - operating_from_rent - heating_from_rent
    operating_advance = operating_from_rent
    heating_advance = direct_heating_advance + heating_from_rent
    non_recurring_shortfall_income = shortfall_income + direct_operating_advance

    rent_advance_delta = rent_income - expected_rent if has_expected else None
    operating_advance_delta = operating_advance - expected_operating_advance if has_expected else None
    heating_advance_delta = heating_advance - expected_heating_advance if has_expected else None

    operating_cost = weg.operating_costs_total if weg else Decimal("0.00")
    heating_cost = weg.heating_costs_total if weg else Decimal("0.00")
    prior_year_balance = weg.prior_year_balance if weg else Decimal("0.00")
    operating_delta = operating_advance - operating_cost
    heating_delta = heating_advance - heating_cost
    net_balance = operating_delta + heating_delta

    window_start, window_end = reporting_window_bounds(report_year)
    return AnnualSettlement(
        report_year=report_year,
        period_start=datetime.date(report_year, 1, 1),
        period_end=datetime.date(report_year, 12, 31),
        window_start=window_start,
        window_end=window_end,
        weg=weg,
        rent_income=rent_income,
        operating_advance=operating_advance,
        heating_advance=heating_advance,
        direct_operating_advance=direct_operating_advance,
        operating_from_rent=operating_from_rent,
        shortfall_income=shortfall_income,
        non_recurring_shortfall_income=non_recurring_shortfall_income,
        has_expected=has_expected,
        expected_rent=expected_rent,
        expected_operating_advance=expected_operating_advance,
        expected_heating_advance=expected_heating_advance,
        rent_advance_delta=rent_advance_delta,
        operating_advance_delta=operating_advance_delta,
        heating_advance_delta=heating_advance_delta,
        operating_cost=operating_cost,
        heating_cost=heating_cost,
        prior_year_balance=prior_year_balance,
        operating_delta=operating_delta,
        heating_delta=heating_delta,
        net_balance=net_balance,
    )


def build_invoice_pdf(report_year: int) -> bytes:
    settlement = build_annual_settlement(report_year)
    period_start = settlement.period_start
    period_end = settlement.period_end

    tenant = get_active_tenant(report_year)
    if tenant is None:
        raise ValueError("No active tenant is configured for this report year.")

    property_obj = tenant.property
    missing = []
    if not property_obj.owner_name:
        missing.append("owner name")
    if not property_obj.owner_address:
        missing.append("owner address")
    if not property_obj.owner_city:
        missing.append("owner city/postcode")
    if not property_obj.street_address:
        missing.append("property street address")
    if not property_obj.suburb:
        missing.append("property city/postcode")
    if missing:
        raise ValueError(f"PDF configuration is incomplete: {', '.join(missing)}.")

    previous_year_amount = settlement.prior_year_balance
    if previous_year_amount <= 0:
        previous_settlement = build_annual_settlement(report_year - 1)
        previous_year_amount = (
            -previous_settlement.net_balance
            if previous_settlement.net_balance < 0
            else Decimal("0.00")
        )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "InvoiceSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13,
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    block_left = ParagraphStyle(
        "HeaderLeft",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=11.5,
        alignment=TA_LEFT,
    )
    block_right = ParagraphStyle(
        "HeaderRight",
        parent=block_left,
        alignment=TA_RIGHT,
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13,
        spaceBefore=4,
        spaceAfter=4,
    )

    def euro(value: Decimal) -> str:
        quantized = to_money(value)
        sign = "-" if quantized < 0 else ""
        number = f"{abs(quantized):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{sign}{number}"

    payment_rows = [
        ["", "Miete", "Wärme und\nWarmwasser", "Betriebskosten", "Rückstandsbetrag"],
        ["Summe", euro(settlement.rent_income), euro(settlement.heating_advance), euro(settlement.operating_advance), euro(settlement.non_recurring_shortfall_income)],
    ]
    consumption_rows = [
        ["Hausverwaltung", euro(-(settlement.weg.net_hausverwaltung if settlement.weg else Decimal("0.00")))],
        ["Grundsteuer", euro(-(settlement.weg.land_tax if settlement.weg else Decimal("0.00")))],
        ["", euro(-settlement.operating_cost)],
        ["Delta-t (Heizkosten)", euro(-(settlement.weg.heating if settlement.weg else Decimal("0.00")))],
        ["Delta-t (Warmwasserkosten)", euro(-(settlement.weg.hot_water if settlement.weg else Decimal("0.00")))],
        ["Delta-t (CO2)", euro(-(settlement.weg.co2 if settlement.weg else Decimal("0.00")))],
        ["Delta-t (Betriebskosten)", euro(-(settlement.weg.service_costs if settlement.weg else Decimal("0.00")))],
        ["Netto Heizkosten, Warmwasser, Strom", euro(-settlement.heating_cost)],
    ]

    include_prior_year_rows = previous_year_amount > 0
    settlement_rows = []
    if include_prior_year_rows:
        settlement_rows.append([f"Nebenkosten {report_year - 1}", "", "", euro(-previous_year_amount)])
        if settlement.non_recurring_shortfall_income > 0:
            settlement_rows.append([f"Zahlung Nebenkosten {report_year - 1}", "", "", euro(settlement.non_recurring_shortfall_income)])
    settlement_rows.extend([
        [f"Umlagefähige Betriebskosten für {report_year}", euro(-settlement.operating_cost), euro(settlement.operating_advance), euro(settlement.operating_delta)],
        [f"Heizkosten, Warmwasser, Strom für {report_year}", euro(-settlement.heating_cost), euro(settlement.heating_advance), euro(settlement.heating_delta)],
        [
            "Summe",
            euro(-(settlement.operating_cost + settlement.heating_cost)),
            euro(
                settlement.operating_advance
                + settlement.heating_advance
                + (settlement.non_recurring_shortfall_income if include_prior_year_rows else Decimal("0.00"))
            ),
            euro(
                settlement.net_balance
                + (settlement.non_recurring_shortfall_income if include_prior_year_rows else Decimal("0.00"))
                - (previous_year_amount if include_prior_year_rows else Decimal("0.00"))
            ),
        ],
    ])

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=30,
        bottomMargin=24,
        title=f"Nebenkosten {report_year}",
    )
    story = [
        Paragraph(f"Nebenkosten {report_year}", title_style),
        Paragraph(f"{period_start:%d.%m.%Y} - {period_end:%d.%m.%Y}", subtitle_style),
        HRFlowable(width="100%", thickness=1.6, color=colors.black, spaceBefore=0, spaceAfter=7),
    ]

    parties = Table(
        [[
            Paragraph(f"{property_obj.owner_name}<br/>{property_obj.owner_address}<br/>{property_obj.owner_city}", block_left),
            Paragraph(f"{tenant.full_name}<br/>{property_obj.street_address}<br/>{property_obj.suburb}", block_right),
        ]],
        colWidths=[260, 260],
    )
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([
        parties,
        HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#777777"), spaceBefore=5, spaceAfter=16),
        Paragraph("Einzahlung", section_style),
    ])

    payment_table = Table(payment_rows, colWidths=[76, 100, 118, 100, 110])
    payment_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9d9d9")),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f3f3f3")),
        ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#8a8a8a")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, 1), "Helvetica-Bold"),
        ("FONTNAME", (1, 1), (-1, 1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([
        payment_table,
        Spacer(1, 12),
        Paragraph("Verbrauch (ggf WEG Bescheinigung)", section_style),
    ])

    consumption_table = Table(consumption_rows, colWidths=[320, 184])
    consumption_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#8a8a8a")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f3f3")),
        ("FONTNAME", (0, 7), (-1, 7), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([
        consumption_table,
        Spacer(1, 12),
        Paragraph("Abrechnung", section_style),
    ])

    settlement_table = Table(
        [["", "Verwaltung", "Bereits eingezahlte\nNebenkosten", "Summe"]] + settlement_rows,
        colWidths=[214, 92, 112, 86],
    )
    settlement_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9d9d9")),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f3f3f3")),
        ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#8a8a8a")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(settlement_table)
    story.append(Spacer(1, 8))

    result_label = "Nachzahlung" if settlement.net_balance < 0 else "Gutschrift"
    result_amount = euro(abs(settlement.net_balance)) + " €"
    result_table = Table([[result_label, result_amount]], colWidths=[426, 78])
    result_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11.5),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(result_table)

    doc.build(story)
    return buffer.getvalue()


def _format_money(value: Decimal) -> str:
    quantized = to_money(value)
    number = f"{abs(quantized):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"-{number}" if quantized < 0 else number


def _city_name(value: str) -> str:
    parts = value.split()
    return parts[-1] if parts else value


def _build_rent_increase_context(report_year: int, planning_data: dict) -> dict:
    settlement = build_annual_settlement(report_year)

    tenant = get_active_tenant(report_year)
    if tenant is None:
        raise ValueError("No active tenant is configured for this report year.")

    property_obj = tenant.property
    missing = []
    if not property_obj.owner_name:
        missing.append("owner name")
    if not property_obj.owner_address:
        missing.append("owner address")
    if not property_obj.owner_city:
        missing.append("owner city/postcode")
    if not property_obj.street_address:
        missing.append("property street address")
    if not property_obj.suburb:
        missing.append("property city/postcode")
    if missing:
        raise ValueError(f"PDF configuration is incomplete: {', '.join(missing)}.")

    def planning_value(key: str, default):
        value = planning_data.get(key)
        return default if value in (None, "") else value

    saved_plan = planning_data.get("saved_plan")
    if saved_plan is not None:
        planning_data = {
            "current_weekly_cold_rent": saved_plan.current_weekly_cold_rent,
            "projected_annual_maintenance_costs": saved_plan.projected_annual_maintenance_costs,
            "projected_annual_utility_costs": saved_plan.projected_annual_utility_costs,
            "mietspiegel_weekly_cold_rent": saved_plan.mietspiegel_weekly_cold_rent,
            "base_increase_percent": saved_plan.base_increase_percent,
            **planning_data,
        }

    current_cold_rent = planning_value(
        "current_weekly_cold_rent",
        resolve_current_cold_rent(tenant, report_year),
    )

    projected_annual_maintenance_costs = planning_value(
        "projected_annual_maintenance_costs",
        settlement.operating_cost,
    )
    projected_annual_utility_costs = planning_value(
        "projected_annual_utility_costs",
        settlement.heating_cost,
    )

    proposal = build_rent_increase_proposal({
        "property_name": property_obj.name,
        "tenant_name": tenant.full_name,
        "current_weekly_cold_rent": current_cold_rent,
        "projected_annual_maintenance_costs": projected_annual_maintenance_costs,
        "projected_annual_utility_costs": projected_annual_utility_costs,
        "mietspiegel_weekly_cold_rent": planning_data["mietspiegel_weekly_cold_rent"],
        "base_increase_percent": planning_value("base_increase_percent", Decimal("5.00")),
    })

    monthly_weg_contribution = round_up_to_increment(
        (projected_annual_maintenance_costs - projected_annual_utility_costs) / Decimal("12")
    )
    monthly_utility_contribution = round_up_to_increment(projected_annual_utility_costs / Decimal("12"))
    current_total_rent = round_up_to_increment(
        proposal.current_weekly_cold_rent + monthly_weg_contribution + monthly_utility_contribution,
        Decimal("1.00"),
    )
    proposed_total_rent = round_up_to_increment(
        proposal.proposed_weekly_rent + monthly_weg_contribution + monthly_utility_contribution,
        Decimal("1.00"),
    )

    return {
        "settlement": settlement,
        "tenant": tenant,
        "property": property_obj,
        "proposal": proposal,
        "letter_date": datetime.date.today(),
        "effective_date": datetime.date(report_year + 1, 1, 1),
        "city_name": _city_name(property_obj.suburb),
        "monthly_weg_contribution": monthly_weg_contribution,
        "monthly_utility_contribution": monthly_utility_contribution,
        "current_total_rent": current_total_rent,
        "proposed_total_rent": proposed_total_rent,
        "saved_plan": saved_plan,
    }


def _build_rent_increase_pdf(title: str, context: dict, body_paragraphs: list[str], summary_rows: list[list[str]], closing_lines: list[str], signature_block: list[str] | None = None) -> bytes:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RentIncreaseTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "RentIncreaseBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        spaceAfter=6,
    )
    block_left = ParagraphStyle(
        "RentIncreaseBlockLeft",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=11.5,
        alignment=TA_LEFT,
    )
    block_right = ParagraphStyle(
        "RentIncreaseBlockRight",
        parent=block_left,
        alignment=TA_RIGHT,
    )
    section_style = ParagraphStyle(
        "RentIncreaseSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13,
        spaceBefore=4,
        spaceAfter=4,
    )

    def euro(value: Decimal) -> str:
        return f"{_format_money(value)} €"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=30,
        bottomMargin=24,
        title=title,
    )

    property_obj = context["property"]
    tenant = context["tenant"]
    proposal = context["proposal"]

    parties = Table(
        [[
            Paragraph(
                f"{property_obj.owner_name}<br/>{property_obj.owner_address}<br/>{property_obj.owner_city}",
                block_left,
            ),
            Paragraph(
                f"{tenant.full_name}<br/>{property_obj.street_address}<br/>{property_obj.suburb}",
                block_right,
            ),
        ]],
        colWidths=[260, 260],
    )
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    story = [
        parties,
        Paragraph(f"{context['city_name']}, {context['letter_date']:%d. %B %Y}", body_style),
        Paragraph(title, title_style),
    ]
    for paragraph in body_paragraphs:
        story.append(Paragraph(paragraph, body_style))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Berechnung", section_style))

    table = Table(summary_rows, colWidths=[240, 220])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9d9d9")),
        ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#8a8a8a")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.8),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([table, Spacer(1, 10)])

    for paragraph in closing_lines:
        story.append(Paragraph(paragraph, body_style))

    if signature_block:
        story.append(Spacer(1, 18))
        for paragraph in signature_block:
            story.append(Paragraph(paragraph, body_style))

    doc.build(story)
    return buffer.getvalue()


def build_rent_increase_notice_pdf(report_year: int, planning_data: dict) -> bytes:
    context = _build_rent_increase_context(report_year, planning_data)
    proposal = context["proposal"]
    effective_date = context["effective_date"]
    notice_date = context["letter_date"]
    tenant_last_name = context["tenant"].full_name.split()[-1]

    body_paragraphs = [
        f"Sehr geehrte Frau {tenant_last_name},",
        (
            f"mit diesem Schreiben kündigen wir die Anpassung der Nettokaltmiete für das Mietobjekt "
            f"{context['property'].name} an. Die Planung basiert auf den aktuellen WEG-Figuren für "
            f"das Jahr {report_year}, einem nominalen Planungsaufschlag von {proposal.base_increase_percent:.2f} % "
            f"und der Mietspiegel-Bewertung aus dem externen Verfahren."
        ),
        (
            f"Ab dem {effective_date:%d.%m.%Y} soll die Nettokaltmiete auf {proposal.proposed_weekly_rent:.2f} € pro Monat "
            f"angepasst werden. Damit erhöht sich die Miete um {proposal.weekly_increase_amount:.2f} € "
            f"gegenüber der bisherigen Nettokaltmiete von {proposal.current_weekly_cold_rent:.2f} €."
        ),
        (
            f"Die monatlichen WEG- und Utility-Beiträge in Höhe von {context['monthly_weg_contribution']:.2f} € "
            f"und {context['monthly_utility_contribution']:.2f} € bleiben unverändert. "
            f"Die neue Gesamtmiete beträgt damit {context['proposed_total_rent']:.2f} € pro Monat."
        ),
        "Bitte prüfen Sie die beigefügte Zustimmungserklärung und senden Sie uns diese unterschrieben zurück.",
        "",
        "Mit freundlichen Grüßen",
        context["property"].owner_name,
    ]

    summary_rows = [
            ["Aktuelle Nettokaltmiete", f"{_format_money(proposal.current_weekly_cold_rent)} €"],
            ["Planungszuschlag", f"{proposal.base_increase_percent:.2f} %"],
            ["Planungszuschlag in €", f"{_format_money(proposal.base_increase_amount)} €"],
            ["WEG-/Utility-Planung pro Jahr", f"{_format_money(proposal.projected_annual_total_costs)} €"],
            ["Mietspiegel-Referenz", f"{_format_money(proposal.mietspiegel_weekly_cold_rent)} €"],
            ["Vorgeschlagene Nettokaltmiete", f"{_format_money(proposal.proposed_weekly_rent)} €"],
            ["Neue Gesamtmiete", f"{_format_money(context['proposed_total_rent'])} €"],
    ]

    closing_lines = [
        f"Hinweis: Diese Anpassung soll ab dem {effective_date:%d.%m.%Y} gelten.",
        f"Planungsstand: {notice_date:%d.%m.%Y}.",
    ]

    return _build_rent_increase_pdf(
        title=f"Mieterhöhung ab {effective_date:%d.%m.%Y}",
        context=context,
        body_paragraphs=body_paragraphs,
        summary_rows=summary_rows,
        closing_lines=closing_lines,
    )


def build_rent_increase_acceptance_pdf(report_year: int, planning_data: dict) -> bytes:
    context = _build_rent_increase_context(report_year, planning_data)
    proposal = context["proposal"]
    effective_date = context["effective_date"]
    city_name = context["city_name"]

    body_paragraphs = [
        f"{city_name}, _____________________",
        context["tenant"].full_name,
        context["property"].street_address,
        context["property"].suburb,
        "",
        "Zustimmungserklärung",
        (
            f"Mit Schreiben vom {context['letter_date']:%d.%m.%Y} wurde mir eine Anhebung der Nettokaltmiete "
            f"für das Mietobjekt {context['property'].name} angekündigt."
        ),
        (
            f"Die neue Miete wird ab dem {effective_date:%d.%m.%Y} insgesamt {context['proposed_total_rent']:.2f} € "
            f"({proposal.proposed_weekly_rent:.2f} € Nettokaltmiete + {context['monthly_weg_contribution']:.2f} € WEG-Beitrag "
            f"+ {context['monthly_utility_contribution']:.2f} € Utility-Beitrag) betragen."
        ),
        (
            f"Hiermit stimme ich der Mieterhöhung zu. Die neue Gesamtmiete werde ich erstmals zum {effective_date:%d.%m.%Y} zahlen."
        ),
    ]

    summary_rows = [
        ["Bisherige Nettokaltmiete", f"{_format_money(proposal.current_weekly_cold_rent)} €"],
        ["Neue Nettokaltmiete", f"{_format_money(proposal.proposed_weekly_rent)} €"],
        ["WEG-Beitrag", f"{_format_money(context['monthly_weg_contribution'])} €"],
        ["Utility-Beitrag", f"{_format_money(context['monthly_utility_contribution'])} €"],
        ["Neue Gesamtmiete", f"{_format_money(context['proposed_total_rent'])} €"],
    ]

    closing_lines = ["Mit freundlichen Grüßen"]
    signature_block = [
        "__________________________________",
        context["tenant"].full_name,
    ]

    return _build_rent_increase_pdf(
        title="Zustimmungserklärung",
        context=context,
        body_paragraphs=body_paragraphs,
        summary_rows=summary_rows,
        closing_lines=closing_lines,
        signature_block=signature_block,
    )


def parse_bank_statement(source_doc):
    """
    Parse an RVB-format bank statement PDF linked to *source_doc*.

    Uses the same extraction algorithm as the pdf2csv RVB adapter:
    - Lines starting with DD.MM. and ending with S (Soll/debit) or H (Haben/credit)
      are transaction headers.
    - Subsequent non-date lines are accumulated as the detail description.
    - Amount is the second-to-last token; S makes it negative.

    Each extracted transaction is matched against all stored StatementPattern
    regexes (first match wins, case-insensitive).  BankTransaction records are
    written to the database, replacing any previously parsed transactions for this
    source document.  The source document's processing_state is updated to IMPORTED.

    Returns the list of created BankTransaction objects.
    """
    from .models import BankTransaction, SourceDocument, StatementPattern

    patterns = list(StatementPattern.objects.all())

    file_path = source_doc.uploaded_file.path
    reader = PdfReader(file_path)

    date_re = re.compile(r"^([0-9]{2}\.){2}")
    year_re = re.compile(r"[0-9]{1,2}/([0-9]{4})")

    raw_rows = []

    for page in reader.pages:
        full_text = page.extract_text() or ""
        year = None
        collecting = False
        row = None

        for line in full_text.splitlines():
            # Try to extract the statement year from a line like "01/2024"
            if not year:
                m = year_re.search(line)
                if m:
                    year = m.group(1)

            if date_re.search(line):
                # Finalise the previous row before starting a new one
                if collecting and row:
                    raw_rows.append(row)
                    collecting = False
                    row = None

                segments = line.split()
                # A transaction header ends with S (debit) or H (credit)
                if segments and re.search(r"^(S|H)$", segments[-1]):
                    try:
                        amount = Decimal(
                            segments[-2].replace(".", "").replace(",", ".")
                        )
                    except Exception:
                        amount = Decimal("0.00")

                    if segments[-1] == "S":
                        amount = -amount

                    collecting = True
                    row = {
                        "date_str": f"{segments[0]}{year or ''}",
                        "amount": amount,
                        "detail": "",
                    }
                else:
                    collecting = False
            else:
                if collecting and row is not None:
                    part = line.strip()
                    if part:
                        row["detail"] = (row["detail"] + " " + part).strip()

        # Finalise any pending row at the end of the page
        if collecting and row:
            raw_rows.append(row)

    # Replace any previously parsed transactions for this source document
    BankTransaction.objects.filter(source_document=source_doc).delete()

    created = []
    for raw in raw_rows:
        detail = " ".join(raw["detail"].split())
        try:
            tx_date = datetime.datetime.strptime(raw["date_str"], "%d.%m.%Y").date()
        except ValueError:
            continue

        matched_pattern = None
        classification = ""
        for pattern in patterns:
            try:
                if re.search(pattern.regex, detail, flags=re.IGNORECASE):
                    matched_pattern = pattern
                    classification = pattern.classification
                    break
            except re.error:
                continue

        # Only store transactions that matched a pattern; unrecognised lines are skipped.
        if matched_pattern is None:
            continue

        bt = BankTransaction.objects.create(
            source_document=source_doc,
            transaction_date=tx_date,
            detail=detail,
            amount=raw["amount"],
            classification=classification,
            matched_pattern=matched_pattern,
        )
        created.append(bt)

    source_doc.processing_state = SourceDocument.ProcessingState.IMPORTED
    source_doc.save(update_fields=["processing_state"])

    return created
