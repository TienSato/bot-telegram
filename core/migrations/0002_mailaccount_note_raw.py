"""Them cot raw_input va note cho MailAccount."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="mailaccount",
            name="raw_input",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="mailaccount",
            name="note",
            field=models.TextField(blank=True, default=""),
        ),
    ]
