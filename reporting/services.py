from dataclasses import dataclass
import datetime
import re
from decimal import Decimal, ROUND_HALF_UP

from pypdf import PdfReader


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
