from django.shortcuts import render

from .forms import YearEndReportDraftForm
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
