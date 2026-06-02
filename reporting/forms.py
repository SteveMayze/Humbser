from django import forms


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


class DocumentUploadForm(forms.Form):
    bank_statements = forms.FileField(
        required=False,
        label="Bank statements",
        help_text="Select up to 12 monthly PDFs, or drag and drop a folder's worth of files.",
    )
    manager_report = forms.FileField(
        required=False,
        label="Property manager report",
        help_text="Annual or end-of-year statement from the property manager.",
    )
    utility_statement = forms.FileField(
        required=False,
        label="Utility statement",
        help_text="Council or utility provider statement covering the reporting period.",
    )

    def clean(self):
        cleaned_data = super().clean()
        if not any([
            cleaned_data.get("bank_statements"),
            cleaned_data.get("manager_report"),
            cleaned_data.get("utility_statement"),
        ]):
            raise forms.ValidationError("Please upload at least one document.")
        return cleaned_data
