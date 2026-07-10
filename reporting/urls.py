from django.urls import path

from .views import (
    add_pattern,
    clear_staged_documents,
    clear_year_data,
    dashboard,
    delete_document,
    delete_pattern,
    download_invoice_pdf,
    reclassify_transaction,
    upload_documents,
)


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("invoice.pdf", download_invoice_pdf, name="download_invoice_pdf"),
    path("upload/", upload_documents, name="upload_documents"),
    path("upload/patterns/add/", add_pattern, name="add_pattern"),
    path("upload/patterns/<int:pattern_id>/delete/", delete_pattern, name="delete_pattern"),
    path("upload/documents/<int:doc_id>/delete/", delete_document, name="delete_document"),
    path("upload/transactions/<int:tx_id>/reclassify/", reclassify_transaction, name="reclassify_transaction"),
    path("upload/clear-staged/", clear_staged_documents, name="clear_staged_documents"),
    path("clear-year/", clear_year_data, name="clear_year_data"),
]
