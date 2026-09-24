"""Initial migration — tao toan bo bang cho Read Mail Bot."""
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        # 1. Bot
        migrations.CreateModel(
            name="Bot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Ten hien thi cua bot", max_length=100)),
                ("token", models.CharField(help_text="Token tu @BotFather", max_length=200, unique=True)),
                ("description", models.TextField(blank=True, default="", help_text="Mo ta ngan")),
                ("is_active", models.BooleanField(default=True, help_text="Bot co dang chay khong")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "verbose_name": "Bot",
                "verbose_name_plural": "Bots",
                "db_table": "bots",
                "ordering": ["-created_at"],
            },
        ),
        # 2. Feature
        migrations.CreateModel(
            name="Feature",
            fields=[
                ("name", models.CharField(max_length=100, primary_key=True, serialize=False)),
                ("description", models.TextField(blank=True, default="")),
                ("enabled", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Feature",
                "verbose_name_plural": "Features",
                "db_table": "features",
            },
        ),
        # 3. TelegramUser
        migrations.CreateModel(
            name="TelegramUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("telegram_id", models.BigIntegerField(db_index=True, unique=True)),
                ("username", models.CharField(blank=True, max_length=255, null=True)),
                ("first_name", models.CharField(blank=True, max_length=255, null=True)),
                ("is_admin", models.BooleanField(default=False)),
                ("is_banned", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("last_active", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "verbose_name": "Telegram User",
                "verbose_name_plural": "Telegram Users",
                "db_table": "telegram_users",
                "ordering": ["-last_active"],
            },
        ),
        # 4. BotSetting
        migrations.CreateModel(
            name="BotSetting",
            fields=[
                ("key", models.CharField(max_length=100, primary_key=True, serialize=False)),
                ("value", models.TextField(blank=True, default="")),
                ("category", models.CharField(choices=[("mail", "Mail"), ("general", "General")], default="general", max_length=50)),
                ("description", models.TextField(blank=True, default="")),
                ("is_secret", models.BooleanField(default=False)),
            ],
            options={
                "verbose_name": "Bot Setting",
                "verbose_name_plural": "Bot Settings",
                "db_table": "bot_settings",
                "ordering": ["category", "key"],
            },
        ),
        # 5. BotFeature
        migrations.CreateModel(
            name="BotFeature",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=True, help_text="Bat/tat chuc nang nay cho bot")),
                ("bot", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bot_features", to="core.bot")),
                ("feature", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bot_features", to="core.feature", to_field="name")),
            ],
            options={
                "verbose_name": "Bot Feature",
                "verbose_name_plural": "Bot Features",
                "db_table": "bot_features",
            },
        ),
        migrations.AddConstraint(
            model_name="botfeature",
            constraint=models.UniqueConstraint(fields=("bot", "feature"), name="uq_bot_feature"),
        ),
        # 6. MailAccount
        migrations.CreateModel(
            name="MailAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=320)),
                ("refresh_token", models.TextField()),
                ("client_id", models.CharField(max_length=255)),
                ("tenant_id", models.CharField(default="consumers", max_length=255)),
                ("added_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="accounts", to="core.telegramuser")),
            ],
            options={
                "verbose_name": "Mail Account",
                "verbose_name_plural": "Mail Accounts",
                "db_table": "mail_accounts",
            },
        ),
        # 7. UserPermission
        migrations.CreateModel(
            name="UserPermission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("allowed", models.BooleanField(default=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="permissions", to="core.telegramuser")),
                ("feature", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="user_permissions", to="core.feature", to_field="name")),
            ],
            options={
                "verbose_name": "User Permission",
                "verbose_name_plural": "User Permissions",
                "db_table": "user_permissions",
            },
        ),
        migrations.AddConstraint(
            model_name="userpermission",
            constraint=models.UniqueConstraint(fields=("user", "feature"), name="uq_user_feature"),
        ),
    ]
