from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0009_rentincreaseplan"),
    ]

    operations = [
        migrations.AddField(
            model_name="rentincreaseplan",
            name="current_weekly_cold_rent",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
