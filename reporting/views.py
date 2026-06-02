import datetime
import json
import re

from django.core.exceptions import SuspiciousOperation
from django.db import models
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import BankStatementUploadForm, WEGReportForm, YearEndReportDraftForm
from .models import BankTransaction, SourceDocument, StatementPattern, WEGReport
from .services import build_report_draft, parse_bank_statement


def dashboard(request):
    from decimal import Decimal
    from django.db.models import Sum

    from .models import BankTransaction

    # Available report years: union of WEGReport years and transaction years
    weg_years = list(
        WEGReport.objects.values_list("report_year", flat=True).order_by("-report_year")
    )
    tx_years = list(
        BankTransaction.objects.dates("transaction_date", "year")
        .values_list("transaction_date__year", flat=True)
        .distinct()
        .order_by("-transaction_date__year")
    )
    available_years = sorted(set(weg_years) | set(tx_years), reverse=True)

    # Default to most recent year with data, or last calendar year
    default_year = available_years[0] if available_years else datetime.date.today().year - 1
    try:
        report_year = int(request.GET.get("year", default_year))
    except (ValueError, TypeError):
        report_year = default_year

    weg = WEGReport.objects.filter(report_year=report_year).first()

    def tx_total(classification):
        result = (
            BankTransaction.objects.filter(
                transaction_date__year=report_year,
                classification=classification,
            ).aggregate(total=Sum("amount"))["total"]
        )
        return result or Decimal("0.00")

    C = StatementPattern.Classification
    zero = Decimal("0.00")

    # Directly classified transaction totals
    tenant_rent_gross = tx_total(C.TENANT_RENT)
    direct_operating_advance = tx_total(C.TENANT_OPERATING)
    direct_heating_advance = tx_total(C.TENANT_HEATING)
    shortfall_income = tx_total(C.TENANT_SHORTFALL)

    # Expected annual amounts from tenancy agreement (monthly × 12)
    has_expected = bool(
        weg and (weg.monthly_rent or weg.monthly_operating_advance or weg.monthly_heating_advance)
    )
    expected_rent = weg.annual_rent if has_expected else Decimal("0")
    expected_operating_advance = weg.annual_operating_advance if has_expected else Decimal("0")
    expected_heating_advance = weg.annual_heating_advance if has_expected else Decimal("0")

    # If tenant pays one bundled monthly amount, split the classified rent stream
    # into the configured annual advance components first.
    operating_from_rent = zero
    heating_from_rent = zero
    if has_expected and tenant_rent_gross > zero:
        operating_from_rent = min(expected_operating_advance, tenant_rent_gross)
        remaining_rent = tenant_rent_gross - operating_from_rent
        heating_from_rent = min(expected_heating_advance, remaining_rent)

    rent_income = tenant_rent_gross - operating_from_rent - heating_from_rent
    # Running-year operating advance should come from the recurring monthly rent stream.
    # Any direct tenant_operating postings are treated as non-recurring prior-year payments.
    operating_advance = operating_from_rent
    heating_advance = direct_heating_advance + heating_from_rent
    non_recurring_shortfall_income = shortfall_income + direct_operating_advance

    rent_advance_delta = rent_income - expected_rent if has_expected else None
    operating_advance_delta = operating_advance - expected_operating_advance if has_expected else None
    heating_advance_delta = heating_advance - expected_heating_advance if has_expected else None

    # WEG cost groups (zero if no report saved for this year)
    operating_cost = weg.operating_costs_total if weg else Decimal("0.00")
    heating_cost = weg.heating_costs_total if weg else Decimal("0.00")

    operating_delta = operating_advance - operating_cost
    heating_delta = heating_advance - heating_cost
    net_balance = operating_delta + heating_delta  # positive = Gutschrift, negative = Nachzahlung

    return render(
        request,
        "reporting/dashboard.html",
        {
            "report_year": report_year,
            "available_years": available_years,
            "weg": weg,
            "rent_income": rent_income,
            "operating_advance": operating_advance,
            "heating_advance": heating_advance,
            "direct_operating_advance": direct_operating_advance,
            "operating_from_rent": operating_from_rent,
            "shortfall_income": shortfall_income,
            "non_recurring_shortfall_income": non_recurring_shortfall_income,
            "has_expected": has_expected,
            "expected_rent": expected_rent,
            "expected_operating_advance": expected_operating_advance,
            "expected_heating_advance": expected_heating_advance,
            "rent_advance_delta": rent_advance_delta,
            "operating_advance_delta": operating_advance_delta,
            "heating_advance_delta": heating_advance_delta,
            "operating_cost": operating_cost,
            "heating_cost": heating_cost,
            "operating_delta": operating_delta,
            "heating_delta": heating_delta,
            "net_balance": net_balance,
        },
    )


def upload_documents(request):
    current_year = datetime.date.today().year
    # Allow the year to be driven by a GET parameter so users can work on past years
    selected_year = int(request.GET.get("year", current_year))

    # Pre-populate WEG form from any existing record for the selected year
    existing_weg = WEGReport.objects.filter(report_year=selected_year).first()
    weg_initial = {"report_year": selected_year}
    if existing_weg:
        weg_initial.update({
            "property_management": existing_weg.property_management,
            "heating": existing_weg.heating,
            "hot_water": existing_weg.hot_water,
            "service_costs": existing_weg.service_costs,
            "co2": existing_weg.co2,
            "land_tax": existing_weg.land_tax,
            "monthly_rent": existing_weg.monthly_rent,
            "monthly_heating_advance": existing_weg.monthly_heating_advance,
            "monthly_operating_advance": existing_weg.monthly_operating_advance,
        })

    upload_form = BankStatementUploadForm()
    weg_form = WEGReportForm(initial=weg_initial)
    saved_weg = None
    uploaded_statements = []

    if request.method == "POST":
        upload_form = BankStatementUploadForm(request.POST, request.FILES)
        weg_form = WEGReportForm(request.POST)
        # Update selected_year from the submitted WEG form year if present
        try:
            selected_year = int(request.POST.get("report_year", selected_year))
        except (ValueError, TypeError):
            pass

        upload_valid = upload_form.is_valid()
        weg_valid = weg_form.is_valid()

        # Save bank statements independently of WEG form validity,
        # so they always appear in the staged list even if WEG data needs correction.
        if upload_valid:
            for pdf in request.FILES.getlist("bank_statements"):
                _validate_pdf_extension(pdf.name)
                doc = SourceDocument(
                    document_type=SourceDocument.DocumentType.BANK_STATEMENT,
                    reference=pdf.name,
                )
                doc.uploaded_file.save(pdf.name, pdf, save=True)
                new_txs = parse_bank_statement(doc)
                uploaded_statements.append((doc, len(new_txs)))

        if weg_valid:
            # Save WEG report data
            saved_weg = weg_form.save_or_update()

    staged = (
        SourceDocument.objects.filter(
            reporting_run__isnull=True,
            document_type=SourceDocument.DocumentType.BANK_STATEMENT,
        )
        .annotate(tx_count=models.Count("transactions"))
        .order_by("-imported_at")
    )

    patterns = list(
        StatementPattern.objects.values("id", "regex", "classification")
    )
    classification_choices = [
        {"value": v, "label": l}
        for v, l in StatementPattern.Classification.choices
    ]
    # Build display labels map for the template
    cls_labels = {v: l for v, l in StatementPattern.Classification.choices}
    for p in patterns:
        p["classification_label"] = cls_labels.get(p["classification"], p["classification"])

    # Transactions for this year (for inline reclassification)
    transactions = list(
        BankTransaction.objects.filter(
            transaction_date__year=selected_year,
        )
        .order_by("transaction_date", "pk")
        .values("id", "transaction_date", "detail", "amount", "classification")
    )
    unclassified_count = sum(1 for t in transactions if not t["classification"])

    return render(
        request,
        "reporting/upload.html",
        {
            "upload_form": upload_form,
            "weg_form": weg_form,
            "current_year": current_year,
            "selected_year": selected_year,
            "staged": staged,
            "patterns": patterns,
            "classification_choices": classification_choices,
            "saved_weg": saved_weg,
            "uploaded_count": len(uploaded_statements),
            "parsed_tx_count": sum(c for _, c in uploaded_statements),
            "transactions": transactions,
            "unclassified_count": unclassified_count,
        },
    )


@require_POST
def add_pattern(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        body = request.POST

    regex = body.get("regex", "").strip()
    classification = body.get("classification", "").strip()

    if not regex:
        return JsonResponse({"error": "Pattern (regex) is required."}, status=400)
    if len(regex) > 255:
        return JsonResponse({"error": "Pattern is too long (max 255 characters)."}, status=400)

    # Validate the regex server-side
    try:
        re.compile(regex)
    except re.error as exc:
        return JsonResponse({"error": f"Invalid regular expression: {exc}"}, status=400)

    valid_classifications = {c for c, _ in StatementPattern.Classification.choices}
    if classification not in valid_classifications:
        return JsonResponse({"error": "Invalid classification."}, status=400)

    pattern, created = StatementPattern.objects.get_or_create(
        regex=regex,
        defaults={"classification": classification},
    )
    return JsonResponse({
        "id": pattern.id,
        "regex": pattern.regex,
        "classification": pattern.classification,
        "classification_label": pattern.get_classification_display(),
        "created": created,
    })


@require_POST
def delete_pattern(request, pattern_id):
    deleted, _ = StatementPattern.objects.filter(pk=pattern_id).delete()
    if deleted:
        return JsonResponse({"success": True})
    return JsonResponse({"error": "Pattern not found."}, status=404)


@require_POST
def delete_document(request, doc_id):
    """Delete a single staged SourceDocument and all its parsed transactions + uploaded file."""
    doc = get_object_or_404(SourceDocument, pk=doc_id, reporting_run__isnull=True)
    BankTransaction.objects.filter(source_document=doc).delete()
    if doc.uploaded_file:
        try:
            doc.uploaded_file.delete(save=False)
        except Exception:
            pass
    doc.delete()
    return JsonResponse({"success": True})


@require_POST
def clear_staged_documents(request):
    """Delete all staged (un-linked) bank statement documents, their files and transactions."""
    staged = SourceDocument.objects.filter(
        reporting_run__isnull=True,
        document_type=SourceDocument.DocumentType.BANK_STATEMENT,
    )
    for doc in staged:
        BankTransaction.objects.filter(source_document=doc).delete()
        if doc.uploaded_file:
            try:
                doc.uploaded_file.delete(save=False)
            except Exception:
                pass
    staged.delete()
    year = request.POST.get("year", "")
    redirect_url = f"/upload/?year={year}" if year else "/upload/"
    return redirect(redirect_url)


@require_POST
def clear_year_data(request):
    """Delete WEGReport and all BankTransactions for the given year.

    Staged SourceDocuments that have no remaining transactions are also deleted.
    """
    try:
        year = int(request.POST.get("year", 0))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid year."}, status=400)

    # Delete transactions for this year
    BankTransaction.objects.filter(transaction_date__year=year).delete()

    # Delete WEG report for this year
    WEGReport.objects.filter(report_year=year).delete()

    # Clean up staged source documents that now have no transactions
    orphaned = SourceDocument.objects.filter(
        reporting_run__isnull=True,
        document_type=SourceDocument.DocumentType.BANK_STATEMENT,
        transactions__isnull=True,
    )
    for doc in orphaned:
        if doc.uploaded_file:
            try:
                doc.uploaded_file.delete(save=False)
            except Exception:
                pass
    orphaned.delete()

    return redirect(f"/?year={year}")


@require_POST
def reclassify_transaction(request, tx_id):
    """AJAX: change the classification of a single BankTransaction."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        body = request.POST

    classification = body.get("classification", "").strip()
    valid_classifications = {c for c, _ in StatementPattern.Classification.choices}
    valid_classifications.add("")  # allow clearing
    if classification not in valid_classifications:
        return JsonResponse({"error": "Invalid classification."}, status=400)

    tx = get_object_or_404(BankTransaction, pk=tx_id)
    tx.classification = classification
    # Clear the automatic pattern link since the user overrode it manually
    tx.matched_pattern = None
    tx.save(update_fields=["classification", "matched_pattern"])
    return JsonResponse({"success": True, "classification": classification})


def _validate_pdf_extension(filename: str) -> None:
    if not filename.lower().endswith(".pdf"):
        from django.core.exceptions import SuspiciousOperation
        raise SuspiciousOperation("Only PDF files are accepted.")
