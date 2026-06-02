from django.db import migrations, models
import django.db.models.deletion


def migrate_tenant_classification(apps, schema_editor):
    """Rename old generic 'tenant' classification to 'tenant_rent'."""
    StatementPattern = apps.get_model("reporting", "StatementPattern")
    StatementPattern.objects.filter(classification="tenant").update(
        classification="tenant_rent"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0004_statementpattern_regex_classification"),
    ]

    operations = [
        # Update choices on the classification field (no DB schema change needed,
        # but recorded here so makemigrations stays clean).
        migrations.AlterField(
            model_name="statementpattern",
            name="classification",
            field=models.CharField(
                choices=[
                    ("tenant_rent", "Tenant \u2014 Rent"),
                    ("tenant_operating", "Tenant \u2014 Operating advance"),
                    ("tenant_heating", "Tenant \u2014 Heating advance"),
                    ("management", "Management"),
                    ("land_tax", "Land tax"),
                    ("affiliations", "Affiliations"),
                ],
                default="tenant_rent",
                max_length=30,
            ),
        ),
        # Migrate any existing 'tenant' records to 'tenant_rent'.
        migrations.RunPython(
            migrate_tenant_classification,
            reverse_code=migrations.RunPython.noop,
        ),
        # Create the BankTransaction table.
        migrations.CreateModel(
            name="BankTransaction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("transaction_date", models.DateField()),
                ("detail", models.TextField()),
                (
                    "amount",
                    models.DecimalField(decimal_places=2, max_digits=10),
                ),
                (
                    "classification",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("tenant_rent", "Tenant \u2014 Rent"),
                            ("tenant_operating", "Tenant \u2014 Operating advance"),
                            ("tenant_heating", "Tenant \u2014 Heating advance"),
                            ("management", "Management"),
                            ("land_tax", "Land tax"),
                            ("affiliations", "Affiliations"),
                        ],
                        default="",
                        max_length=30,
                    ),
                ),
                (
                    "matched_pattern",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="transactions",
                        to="reporting.statementpattern",
                    ),
                ),
                (
                    "source_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transactions",
                        to="reporting.sourcedocument",
                    ),
                ),
            ],
            options={
                "ordering": ["transaction_date"],
            },
        ),
    ]
