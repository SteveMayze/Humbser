from django.urls import path

from .views import dashboard, upload_documents


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("upload/", upload_documents, name="upload_documents"),
]
