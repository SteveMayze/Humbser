from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0003_add_statement_pattern_weg_report"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="statementpattern",
            name="name",
        ),
        migrations.AddField(
            model_name="statementpattern",
            name="regex",
            field=models.CharField(
                default="",
                help_text="Python-compatible regular expression matched against the transaction description.",
                max_length=255,
                unique=True,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="statementpattern",
            name="classification",
            field=models.CharField(
                choices=[
                    ("tenant", "Tenant"),
                    ("management", "Management"),
                    ("land_tax", "Land tax"),
                    ("affiliations", "Affiliations"),
                ],
                default="tenant",
                max_length=30,
            ),
        ),
        migrations.AlterModelOptions(
            name="statementpattern",
            options={"ordering": ["classification", "regex"]},
        ),
    ]
