# Humbser

A Django app to help with end-of-year rental reporting.

## Current scope

This repository now contains the initial Django framework for:

- storing properties, tenants, reporting runs and supporting source documents
- drafting an end-of-year utility shortfall calculation
- estimating the next weekly rent using the council-guided percentage increase
- producing a draft tenant letter that explains the shortfall and rent increase

The document ingestion flow is intentionally scaffolded rather than fully implemented.
Bank statements, property manager statements and council rental reports can be tracked as
`SourceDocument` records, and each document includes a `parser_hint` field for future PDF
ingestion work such as the `pdf2csv` project.

The reporting dashboard can also export a one-page PDF invoice for the selected report year.
Configure the landlord header details on the `Property` record in Django admin, and ensure
there is an active `Tenant` linked to that property for the report year you want to export.

## Local development

```bash
python3 -m pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py runserver
```

Open `http://127.0.0.1:8000/` to use the draft reporting screen and
`http://127.0.0.1:8000/admin/` for Django admin.

## Testing

```bash
python3 manage.py test
```

## Local source documents

Place private sample PDFs and other test inputs in the local `_secrets_/` directory.
It is ignored by git so documents can be used for local parser development without being committed.
