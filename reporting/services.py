from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


TWOPLACES = Decimal("0.01")


def to_money(value):
    return Decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ReportDraft:
    property_name: str
    tenant_name: str
    report_year: int
    utility_shortfall: Decimal
    proposed_weekly_rent: Decimal
    increase_reason: str
    letter_text: str


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
