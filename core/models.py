"""Django models — Read Mail Bot.

Ho tro nhieu bot, moi bot gan voi cac chuc nang rieng.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone


class Bot(models.Model):
    """Bot Telegram — moi bot co token rieng va gan voi cac chuc nang rieng."""

    name = models.CharField(max_length=100, help_text="Ten hien thi cua bot")
    token = models.CharField(max_length=200, unique=True, help_text="Token tu @BotFather")
    description = models.TextField(blank=True, default="", help_text="Mo ta ngan")
    is_active = models.BooleanField(default=True, help_text="Bot co dang chay khong")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "bots"
        verbose_name = "Bot"
        verbose_name_plural = "Bots"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        status = "ON" if self.is_active else "OFF"
        return f"{self.name} [{status}]"


class BotFeature(models.Model):
    """Gan chuc nang cho bot — moi bot chi chay cac chuc nang duoc gan."""

    bot = models.ForeignKey(
        Bot,
        on_delete=models.CASCADE,
        related_name="bot_features",
    )
    feature = models.ForeignKey(
        "Feature",
        on_delete=models.CASCADE,
        related_name="bot_features",
        to_field="name",
    )
    enabled = models.BooleanField(default=True, help_text="Bat/tat chuc nang nay cho bot")

    class Meta:
        db_table = "bot_features"
        verbose_name = "Bot Feature"
        verbose_name_plural = "Bot Features"
        constraints = [
            models.UniqueConstraint(
                fields=["bot", "feature"],
                name="uq_bot_feature",
            ),
        ]

    def __str__(self) -> str:
        status = "ON" if self.enabled else "OFF"
        return f"{self.bot.name} — {self.feature_id} [{status}]"


class TelegramUser(models.Model):
    """Nguoi dung Telegram."""

    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=255, blank=True, null=True)
    first_name = models.CharField(max_length=255, blank=True, null=True)
    is_admin = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    last_active = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "telegram_users"
        verbose_name = "Telegram User"
        verbose_name_plural = "Telegram Users"
        ordering = ["-last_active"]

    def __str__(self) -> str:
        name = self.username or self.first_name or str(self.telegram_id)
        return f"{name} ({self.telegram_id})"


class MailAccount(models.Model):
    """Tai khoan mail lien ket voi nguoi dung."""

    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="accounts",
    )
    email = models.EmailField(max_length=320)
    refresh_token = models.TextField()
    client_id = models.CharField(max_length=255)
    tenant_id = models.CharField(max_length=255, default="consumers")
    # Nguyen van dong user nhap (email|password|refresh_token|client_id[|tenant_id])
    # de xuat lai y het luc nhap. Khong dung de xac thuc.
    raw_input = models.TextField(blank=True, default="")
    # Ghi chu cua user cho tai khoan nay
    note = models.TextField(blank=True, default="")
    added_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "mail_accounts"
        verbose_name = "Mail Account"
        verbose_name_plural = "Mail Accounts"

    def __str__(self) -> str:
        return self.email


class Feature(models.Model):
    """Tinh nang cua bot, co the bat/tat toan cuc."""

    name = models.CharField(max_length=100, primary_key=True)
    description = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "features"
        verbose_name = "Feature"
        verbose_name_plural = "Features"

    def __str__(self) -> str:
        status = "ON" if self.enabled else "OFF"
        return f"{self.name} [{status}]"


class BotSetting(models.Model):
    """Cau hinh chung luu trong database, quan ly qua admin panel."""

    CATEGORY_CHOICES = [
        ("mail", "Mail"),
        ("general", "General"),
    ]

    key = models.CharField(max_length=100, primary_key=True)
    value = models.TextField(blank=True, default="")
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default="general")
    description = models.TextField(blank=True, default="")
    is_secret = models.BooleanField(default=False)

    class Meta:
        db_table = "bot_settings"
        verbose_name = "Bot Setting"
        verbose_name_plural = "Bot Settings"
        ordering = ["category", "key"]

    def __str__(self) -> str:
        return f"{self.key} ({self.category})"


class UserPermission(models.Model):
    """Quyen truy cap tinh nang cua tung nguoi dung."""

    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="permissions",
    )
    feature = models.ForeignKey(
        Feature,
        on_delete=models.CASCADE,
        related_name="user_permissions",
        to_field="name",
    )
    allowed = models.BooleanField(default=True)

    class Meta:
        db_table = "user_permissions"
        verbose_name = "User Permission"
        verbose_name_plural = "User Permissions"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "feature"],
                name="uq_user_feature",
            ),
        ]

    def __str__(self) -> str:
        status = "YES" if self.allowed else "NO"
        return f"{self.user} - {self.feature_id} [{status}]"
