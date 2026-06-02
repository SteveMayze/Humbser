from django.shortcuts import render, redirect

from .forms import YearEndReportDraftForm, DocumentUploadForm
from .models import SourceDocument
from .services import build_report_draft


def dashboard(request):
    form = YearEndReportDraftForm(request.POST or None)
    draft = None

    if request.method == "POST" and form.is_valid():
        draft = build_report_draft(form.cleaned_data)

    return render(
        request,
        "reporting/dashboard.html",
        {
            "form": form,
            "draft": draft,
        },
    )


def upload_documents(request):
    form = DocumentUploadForm(request.POST or None, request.FILES or None)
    uploaded = []

    if request.method == "POST" and form.is_valid():
        # Bank statements – multiple files share the same field name
        for pdf in request.FILES.getlist("bank_statements"):
            _validate_pdf_extension(pdf.name)
            doc = SourceDocument(
                document_type=SourceDocument.DocumentType.BANK_STATEMENT,
                reference=pdf.name,
            )
            doc.uploaded_file.save(pdf.name, pdf, save=True)
            uploaded.append(doc)

        for field_name, doc_type in [
            ("manager_report", SourceDocument.DocumentType.PROPERTY_MANAGER),
            ("utility_statement", SourceDocument.DocumentType.UTILITY_STATEMENT),
        ]:
            pdf = request.FILES.get(field_name)
            if pdf:
                _validate_pdf_extension(pdf.name)
                doc = SourceDocument(
                    document_type=doc_type,
                    reference=pdf.name,
                )
                doc.uploaded_file.save(pdf.name, pdf, save=True)
                uploaded.append(doc)

        return render(
            request,
            "reporting/upload.html",
            {"form": DocumentUploadForm(), "uploaded": uploaded},
        )

    staged = SourceDocument.objects.filter(reporting_run__isnull=True).order_by("-imported_at")
    return render(
        request,
        "reporting/upload.html",
        {"form": form, "staged": staged},
    )


def _validate_pdf_extension(filename: str) -> None:
    if not filename.lower().endswith(".pdf"):
        from django.core.exceptions import SuspiciousOperation
        raise SuspiciousOperation("Only PDF files are accepted.")
