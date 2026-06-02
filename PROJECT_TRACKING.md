# Project Tracking

## Current Phase
Initial proof of concept validated with real test data.

## Roadmap

### 1. Generate Tenant-Facing PDFs
Goal: Generate final documents from structured data and templates, aligned with samples in `_secrets_/Deliverables`.

Reference samples:
- `_secrets_/Deliverables/Bahar Konci Mieterhoehung 2026.pdf`
- `_secrets_/Deliverables/Bahar Konci Nebenkosten Abrechnung 2024.pdf`
- `_secrets_/Deliverables/Bahar Konci Zustimmungserklaerung 2026.pdf`
- `_secrets_/Deliverables/Rechnung FY24.pdf`

Planned work:
- Define canonical data model for each output document type.
- Build HTML templates for each letter/report with print-first CSS.
- Add deterministic PDF rendering pipeline from app data.
- Add preview + download actions in UI.
- Add regression tests to compare generated output structure/content.

Open questions:
- Are these four templates final, or do variants per tenant/property need to be supported?
- Should generated PDFs be stored on disk, in DB/file storage, or generated on demand only?

### 2. Next-Year Planning Form and Rent Projection
Goal: Add planning workflow for upcoming year costs and rent changes, and feed those values into letter generation.

Inputs required:
- New umlagefaehige Betriebskosten from property manager report.
- Predicted Delta-T total from property manager report.
- Rough Kaltmiete percentage increase.
- Mietspiegel recommendation for Fuerth (format/spec pending).

Planned work:
- Create `PlanningScenario` model scoped by target year.
- Add form for entering planning inputs and assumptions.
- Calculate projected tenant impact (monthly and annual).
- Connect projected values to generated Mieterhoehung and Zustimmungserklaerung letters.
- Keep planned vs actual values separate from final annual settlement data.

Open questions:
- Confirm exact Mietspiegel data shape and update frequency.
- Confirm whether percentage increase is hard cap, target, or advisory.

### 3. UI and Usability Improvements
Goal: Make year navigation and workflow consistency predictable across Dashboard and Upload pages.

Planned work:
- Persist selected year consistently across page transitions.
- Keep year context in links/actions (dashboard <-> upload <-> clear/delete flows).
- Reduce ambiguity in labels for recurring vs non-recurring payments.
- Add lightweight guidance for required classification patterns.

## Milestones

### Milestone A: Reporting Baseline Hardening
- [ ] Complete additional test cases for income classification and settlement math.
- [ ] Add regression tests for year-specific dashboard figures.
- [ ] Verify edge cases with missing months and partial-year tenancy.

### Milestone B: PDF Output MVP
- [ ] First end-to-end generation for all 4 sample deliverables.
- [ ] Manual validation against sample document layout/content.
- [ ] Iteration pass for formatting and legal wording placeholders.

### Milestone C: Planning and Forecasting
- [ ] Planning form implemented with stored scenarios.
- [ ] Projection outputs integrated into letter generation.
- [ ] Review workflow for owner sign-off.

### Milestone D: UX Consistency
- [ ] Year selection consistency completed across all primary pages.
- [ ] Clear distinction between recurring advances and prior-year one-off payments.
- [ ] Fewer manual corrections needed after parser/classification pass.

## Immediate Next Steps
1. Lock PDF generation stack and output approach (HTML-to-PDF strategy and template architecture).
2. Add unit tests around the current settlement and income split logic.
3. Implement year-context persistence improvements between Dashboard and Upload pages.
