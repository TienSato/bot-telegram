"""Async CRUD helpers — wrap Django ORM cho bot handlers.

Django 5 ho tro async ORM: aget_or_create, acreate, adelete, aupdate,
acount, afirst, async for queryset, v.v.

Cac ham nay KHONG can session hay commit — Django tu quan ly transaction.
Bot handlers chi can: await get_user_accounts(user_id)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from core.models import (
    Bot,
    BotFeature,
    BotSetting,
    Feature,
    MailAccount,
    TelegramUser,
    UserPermission,
)


# ── Cau hinh mac dinh ──────────────────────────────────────────────────────

DEFAULT_SETTINGS: list[dict] = [
    {
        "key": "MAX_MAIL_WORKERS",
        "value": "10",
        "category": "mail",
        "description": (
            "So luong worker xu ly mail dong thoi (1-100). "
            "Doi xong co hieu luc sau toi da 30 giay, khong can restart."
        ),
        "is_secret": False,
    },
    {
        "key": "TOKEN_EXCHANGE_CONCURRENCY",
        "value": "4",
        "category": "mail",
        "description": (
            "So luong dong thoi khi doi token Microsoft (1-50). "
            "Doi xong co hieu luc sau toi da 30 giay, khong can restart."
        ),
        "is_secret": False,
    },
    {
        "key": "BOT_CHECK_INTERVAL",
        "value": "10",
        "category": "general",
        "description": (
            "Khoang thoi gian (giay) kiem tra thay doi bot (3-3600). "
            "Doi xong co hieu luc ngay o vong kiem tra ke tiep."
        ),
        "is_secret": False,
    },
    {
        "key": "PUBLIC_BASE_URL",
        "value": os.getenv("PUBLIC_BASE_URL", ""),
        "category": "general",
        "description": (
            "Dia chi web cong khai, dung cho nut mo webview xem mail. "
            "VD: https://ten-mien-cua-ban.com (bat buoc https de mo trong Telegram)"
        ),
        "is_secret": False,
    },
]


# ── Bot ─────────────────────────────────────────────────────────────────────


async def get_active_bots() -> list[Bot]:
    """Lay danh sach cac bot dang hoat dong."""
    return [b async for b in Bot.objects.filter(is_active=True)]


async def get_bot_feature_names(bot_id: int) -> list[str]:
    """Lay danh sach ten cac chuc nang duoc gan cho bot."""
    return [
        bf.feature_id
        async for bf in BotFeature.objects.filter(
            bot_id=bot_id,
            enabled=True,
        )
    ]


# ── TelegramUser ────────────────────────────────────────────────────────────


async def get_or_create_user(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> TelegramUser:
    """Lay nguoi dung theo telegram_id, tao moi neu chua ton tai."""
    user, created = await TelegramUser.objects.aget_or_create(
        telegram_id=telegram_id,
        defaults={
            "username": username,
            "first_name": first_name,
        },
    )
    if not created:
        # Cap nhat thong tin moi nhat
        update_fields = []
        if user.username != username:
            user.username = username
            update_fields.append("username")
        if user.first_name != first_name:
            user.first_name = first_name
            update_fields.append("first_name")
        if update_fields:
            await user.asave(update_fields=update_fields)
    return user


async def update_last_active(user: TelegramUser) -> None:
    """Cap nhat thoi gian hoat dong cuoi cung."""
    user.last_active = datetime.now(timezone.utc)
    await user.asave(update_fields=["last_active"])


# ── MailAccount ─────────────────────────────────────────────────────────────


async def get_user_accounts(user_id: int) -> list[MailAccount]:
    """Lay danh sach tai khoan mail cua nguoi dung."""
    return [
        acc
        async for acc in MailAccount.objects.filter(
            user_id=user_id,
        ).order_by("id")
    ]


async def add_mail_account(
    user_id: int,
    email: str,
    refresh_token: str,
    client_id: str,
    tenant_id: str = "consumers",
    raw_input: str = "",
) -> MailAccount:
    """Them tai khoan mail moi cho nguoi dung.

    raw_input: nguyen van dong user nhap, de sau nay xuat lai y het.
    """
    return await MailAccount.objects.acreate(
        user_id=user_id,
        email=email,
        refresh_token=refresh_token,
        client_id=client_id,
        tenant_id=tenant_id,
        raw_input=raw_input,
    )


async def set_account_note(account_id: int, note: str) -> None:
    """Cap nhat ghi chu cho mot tai khoan mail."""
    await MailAccount.objects.filter(id=account_id).aupdate(note=note)


async def remove_mail_account(account_id: int) -> bool:
    """Xoa tai khoan mail theo id. Tra ve True neu da xoa."""
    deleted, _ = await MailAccount.objects.filter(id=account_id).adelete()
    return deleted > 0


async def remove_all_mail_accounts(user_id: int) -> int:
    """Xoa toan bo tai khoan mail cua mot nguoi dung. Tra ve so luong da xoa."""
    deleted, _ = await MailAccount.objects.filter(user_id=user_id).adelete()
    return deleted


# ── Feature ─────────────────────────────────────────────────────────────────


async def get_all_features() -> list[Feature]:
    """Lay danh sach tat ca cac tinh nang."""
    return [f async for f in Feature.objects.order_by("name")]


async def set_feature_enabled(feature_name: str, enabled: bool) -> None:
    """Bat hoac tat mot tinh nang toan cuc."""
    await Feature.objects.filter(name=feature_name).aupdate(enabled=enabled)


# ── UserPermission ──────────────────────────────────────────────────────────


async def get_user_permission(user_id: int, feature_name: str) -> bool:
    """
    Kiem tra quyen truy cap tinh nang cua nguoi dung.
    Tra ve True neu:
      - Tinh nang duoc bat toan cuc
      - VA (khong co ban ghi UserPermission HOAC ban ghi co allowed=True)
      - VA nguoi dung khong bi chan
    """
    # Kiem tra nguoi dung co bi chan khong
    user = await TelegramUser.objects.filter(id=user_id).values_list("is_banned", flat=True).afirst()
    if user is None or user:
        return False

    # Kiem tra tinh nang co duoc bat toan cuc khong
    feature = await Feature.objects.filter(name=feature_name).values_list("enabled", flat=True).afirst()
    if feature is None or not feature:
        return False

    # Kiem tra quyen rieng cua nguoi dung
    perm = await UserPermission.objects.filter(
        user_id=user_id,
        feature_id=feature_name,
    ).values_list("allowed", flat=True).afirst()

    # Neu khong co ban ghi quyen -> mac dinh cho phep
    if perm is None:
        return True

    return perm


async def set_user_permission(
    user_id: int, feature_name: str, allowed: bool,
) -> None:
    """Dat quyen truy cap tinh nang cho nguoi dung."""
    await UserPermission.objects.aupdate_or_create(
        user_id=user_id,
        feature_id=feature_name,
        defaults={"allowed": allowed},
    )


async def get_user_permissions(user_id: int) -> list[dict]:
    """Lay danh sach quyen cua nguoi dung."""
    features = [f async for f in Feature.objects.order_by("name")]

    perms = {}
    async for p in UserPermission.objects.filter(user_id=user_id):
        perms[p.feature_id] = p.allowed

    permissions = []
    for feature in features:
        allowed = perms.get(feature.name, True)
        permissions.append({
            "feature_name": feature.name,
            "allowed": allowed,
            "feature_enabled": feature.enabled,
        })

    return permissions


# ── BotSetting ──────────────────────────────────────────────────────────────


async def get_setting(key: str) -> str | None:
    """Lay gia tri cau hinh theo key. Tra ve None neu khong ton tai."""
    setting = await BotSetting.objects.filter(key=key).values_list("value", flat=True).afirst()
    return setting


async def get_all_settings() -> list[BotSetting]:
    """Lay tat ca cau hinh, sap xep theo category va key."""
    return [s async for s in BotSetting.objects.order_by("category", "key")]


async def set_setting(key: str, value: str) -> None:
    """Cap nhat gia tri cau hinh. Chi cap nhat neu key da ton tai."""
    await BotSetting.objects.filter(key=key).aupdate(value=value)


async def init_default_settings() -> None:
    """Tao cac cau hinh mac dinh neu chua ton tai trong database."""
    for item in DEFAULT_SETTINGS:
        await BotSetting.objects.aget_or_create(
            key=item["key"],
            defaults={
                "value": item["value"],
                "category": item["category"],
                "description": item["description"],
                "is_secret": item["is_secret"],
            },
        )


async def init_default_features(features: dict) -> None:
    """Tao cac tinh nang mac dinh tu FeatureRegistry neu chua ton tai."""
    for name, info in features.items():
        await Feature.objects.aget_or_create(
            name=name,
            defaults={
                "description": info.description,
                "enabled": True,
            },
        )
