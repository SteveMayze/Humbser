import datetime
import json
import re
from decimal import Decimal

from django.core.exceptions import SuspiciousOperation
from django.db import models
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import BankStatementUploadForm, InvoiceSettingsForm, RentIncreasePlanningForm, WEGReportForm, YearEndReportDraftForm
from .models import BankTransaction, RentIncreasePlan, SourceDocument, StatementPattern, WEGReport
from .services import (
    build_annual_settlement,
    build_invoice_pdf,
    build_report_draft,
    build_rent_increase_proposal,
    build_rent_increase_acceptance_pdf,
    build_rent_increase_notice_pdf,
    get_active_tenant,
    parse_bank_statement,
    reporting_window_bounds,
    round_up_to_increment,
    resolve_current_cold_rent,
    with_reporting_window,
)

def _build_planning_preview(settlement, tenant, planning_data):
    if tenant is None:
        return None

    current_cold_rent = planning_data.get("current_weekly_cold_rent") or Decimal("0.00")
    projected_annual_weg_total = planning_data["projected_annual_maintenance_costs"] or Decimal("0.00")
    projected_annual_utility_costs = planning_data["projected_annual_utility_costs"] or Decimal("0.00")

    proposal = build_rent_increase_proposal(
        {
            "property_name": tenant.property.name,
            "tenant_name": tenant.full_name,
            "current_weekly_cold_rent": current_cold_rent,
            "projected_annual_maintenance_costs": projected_annual_weg_total,
            "projected_annual_utility_costs": Decimal("0.00"),
            "mietspiegel_weekly_cold_rent": planning_data["mietspiegel_weekly_cold_rent"],
            "base_increase_percent": planning_data["base_increase_percent"],
        }
    )

    monthly_weg_contribution = round_up_to_increment(
        (projected_annual_weg_total - projected_annual_utility_costs) / Decimal("12")
    )
    monthly_utility_contribution = round_up_to_increment(projected_annual_utility_costs / Decimal("12"))
    total_monthly_rent = round_up_to_increment(
        proposal.proposed_weekly_rent + monthly_weg_contribution + monthly_utility_contribution,
        Decimal("1.00"),
    )

    return {
        "current_cold_rent": current_cold_rent,
        "proposed_cold_rent": proposal.proposed_weekly_rent,
        "cold_rent_increase": proposal.weekly_increase_amount,
        "monthly_weg_contribution": monthly_weg_contribution,
        "monthly_utility_contribution": monthly_utility_contribution,
        "total_monthly_rent": total_monthly_rent,
        "projected_annual_weg_total": projected_annual_weg_total,
        "projected_annual_utility_costs": projected_annual_utility_costs,
    }


def dashboard(request):
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

    settlement = build_annual_settlement(report_year)
    existing_plan = RentIncreasePlan.objects.filter(report_year=report_year).first()
    active_tenant = get_active_tenant(report_year)
    planning_initial = {
        "report_year": report_year,
        "current_weekly_cold_rent": (
            existing_plan.current_weekly_cold_rent
            if existing_plan and existing_plan.current_weekly_cold_rent > 0
            else (active_tenant.weekly_rent if active_tenant and active_tenant.weekly_rent > 0 else None)
        ),
        "projected_annual_maintenance_costs": settlement.weg.property_management if settlement.weg else settlement.operating_cost,
        "projected_annual_utility_costs": settlement.heating_cost,
        "mietspiegel_weekly_cold_rent": settlement.weg.monthly_rent if settlement.weg else Decimal("0.00"),
        "base_increase_percent": Decimal("5.00"),
    }
    if existing_plan:
        planning_initial.update({
            "current_weekly_cold_rent": existing_plan.current_weekly_cold_rent,
            "projected_annual_maintenance_costs": existing_plan.projected_annual_maintenance_costs,
            "projected_annual_utility_costs": existing_plan.projected_annual_utility_costs,
            "mietspiegel_weekly_cold_rent": existing_plan.mietspiegel_weekly_cold_rent,
            "base_increase_percent": existing_plan.base_increase_percent,
        })
    planning_form = RentIncreasePlanningForm(initial=planning_initial)
    planning_preview = _build_planning_preview(settlement, active_tenant, planning_initial)

    if request.method == "POST":
        planning_form = RentIncreasePlanningForm(request.POST)
        if planning_form.is_valid():
            planning_form.save_or_update()
            return redirect(f"/?year={planning_form.cleaned_data['report_year']}&saved=1#rent-increase-planning")
        planning_preview = _build_planning_preview(settlement, active_tenant, planning_form.cleaned_data)

    context = settlement.__dict__.copy()
    context.update({
        "report_year": report_year,
        "available_years": available_years,
        "planning_form": planning_form,
        "planning_preview": planning_preview,
        "planning_ready": active_tenant is not None,
        "planning_saved": bool(existing_plan),
    })

    return render(
        request,
        "reporting/dashboard.html",
        context,
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
            "prior_year_balance": existing_weg.prior_year_balance,
            "monthly_rent": existing_weg.monthly_rent,
            "monthly_heating_advance": existing_weg.monthly_heating_advance,
            "monthly_operating_advance": existing_weg.monthly_operating_advance,
        })

    active_tenant = get_active_tenant(selected_year)
    invoice_initial = {"report_year": selected_year}
    if active_tenant is not None:
        property_obj = active_tenant.property
        invoice_initial.update({
            "owner_name": property_obj.owner_name,
            "owner_address": property_obj.owner_address,
            "owner_city": property_obj.owner_city,
            "property_name": property_obj.name,
            "property_street_address": property_obj.street_address,
            "property_city": property_obj.suburb,
            "tenant_name": active_tenant.full_name,
        })

    upload_form = BankStatementUploadForm()
    weg_form = WEGReportForm(initial=weg_initial)
    invoice_form = InvoiceSettingsForm(initial=invoice_initial)
    saved_weg = None
    saved_invoice_settings = False
    uploaded_statements = []

    if request.method == "POST":
        upload_form = BankStatementUploadForm(request.POST, request.FILES)
        weg_form = WEGReportForm(request.POST)
        # Update selected_year from the submitted WEG form year if present
        try:
            selected_year = int(request.POST.get("report_year", selected_year))
        except (ValueError, TypeError):
            pass

        invoice_has_input = any(
            request.POST.get(name, "").strip()
            for name in (
                "owner_name",
                "owner_address",
                "owner_city",
                "property_name",
                "property_street_address",
                "property_city",
                "tenant_name",
            )
        )
        invoice_form = InvoiceSettingsForm(request.POST if invoice_has_input else None, initial=invoice_initial)

        upload_valid = upload_form.is_valid()
        weg_valid = weg_form.is_valid()
        invoice_valid = invoice_form.is_valid() if invoice_has_input else False

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

        if invoice_valid:
            invoice_form.save_or_update()
            saved_invoice_settings = True

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

    # Transactions in the reporting window (for inline reclassification)
    window_start, window_end = reporting_window_bounds(selected_year)
    transactions = list(
        with_reporting_window(BankTransaction.objects, selected_year)
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
            "invoice_form": invoice_form,
            "current_year": current_year,
            "selected_year": selected_year,
            "staged": staged,
            "patterns": patterns,
            "classification_choices": classification_choices,
            "saved_weg": saved_weg,
            "saved_invoice_settings": saved_invoice_settings,
            "uploaded_count": len(uploaded_statements),
            "parsed_tx_count": sum(c for _, c in uploaded_statements),
            "transactions": transactions,
            "unclassified_count": unclassified_count,
            "window_start": window_start,
            "window_end": window_end,
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


def download_invoice_pdf(request):
    current_year = datetime.date.today().year
    default_year = current_year - 1
    try:
        report_year = int(request.GET.get("year", default_year))
    except (ValueError, TypeError):
        return HttpResponseBadRequest("Invalid year.")

    try:
        pdf_bytes = build_invoice_pdf(report_year)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="nebenkosten-{report_year}.pdf"'
    return response


def _planning_data_from_request(request):
    try:
        report_year = int(request.GET.get("year", datetime.date.today().year - 1))
    except (ValueError, TypeError):
        raise ValueError("Invalid year.")

    plan = RentIncreasePlan.objects.filter(report_year=report_year).first()
    payload = {
        "report_year": report_year,
        "current_weekly_cold_rent": plan.current_weekly_cold_rent if plan else None,
        "projected_annual_maintenance_costs": plan.projected_annual_maintenance_costs if plan else None,
        "projected_annual_utility_costs": plan.projected_annual_utility_costs if plan else None,
        "mietspiegel_weekly_cold_rent": plan.mietspiegel_weekly_cold_rent if plan else None,
        "base_increase_percent": plan.base_increase_percent if plan else Decimal("5.00"),
        "saved_plan": plan,
    }
    payload.update({
        key: request.GET.get(key)
        for key in (
            "current_weekly_cold_rent",
            "projected_annual_maintenance_costs",
            "projected_annual_utility_costs",
            "mietspiegel_weekly_cold_rent",
            "base_increase_percent",
        )
        if request.GET.get(key) not in (None, "")
    })

    if payload.get("mietspiegel_weekly_cold_rent") in (None, ""):
        raise ValueError("Mietspiegel weekly cold rent is required.")

    form = RentIncreasePlanningForm(payload)
    if not form.is_valid():
        raise ValueError("Invalid rent planning inputs.")
    return form.cleaned_data


def download_rent_increase_letter_pdf(request):
    current_year = datetime.date.today().year
    default_year = current_year - 1
    try:
        report_year = int(request.GET.get("year", default_year))
    except (ValueError, TypeError):
        return HttpResponseBadRequest("Invalid year.")

    try:
        planning_data = _planning_data_from_request(request)
        pdf_bytes = build_rent_increase_notice_pdf(report_year, planning_data)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="mieterhoehung-{report_year}.pdf"'
    return response


def download_rent_increase_acceptance_pdf(request):
    current_year = datetime.date.today().year
    default_year = current_year - 1
    try:
        report_year = int(request.GET.get("year", default_year))
    except (ValueError, TypeError):
        return HttpResponseBadRequest("Invalid year.")

    try:
        planning_data = _planning_data_from_request(request)
        pdf_bytes = build_rent_increase_acceptance_pdf(report_year, planning_data)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="zustimmungserklaerung-{report_year}.pdf"'
    return response


def _validate_pdf_extension(filename: str) -> None:
    if not filename.lower().endswith(".pdf"):
        from django.core.exceptions import SuspiciousOperation
        raise SuspiciousOperation("Only PDF files are accepted.")
