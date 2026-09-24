"""Cac lenh chung — /start, /help, /id, /features.

Trong nhom: phan hoi cac lenh thong tin tu xoa sau INFO_TTL giay de khong spam.
Tin nhan LENH cua user duoc xoa boi CommandCleanupMiddleware.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.db import get_user_permissions
from core.models import TelegramUser
from features.registry import FeatureRegistry

logger = logging.getLogger(__name__)

# Router cho cac lenh chung
common_router = Router(name="common")

# Thoi gian (giay) tu xoa phan hoi lenh thong tin trong NHOM
INFO_TTL = 60


async def _auto_delete(msg: Message, delay: int) -> None:
    """Cho `delay` giay roi xoa tin (bo qua loi)."""
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass


async def _reply_info(message: Message, text: str, is_group: bool) -> Message:
    """Gui phan hoi thong tin; trong nhom thi tu xoa sau INFO_TTL giay."""
    sent = await message.answer(text, parse_mode="HTML")
    if is_group:
        asyncio.create_task(_auto_delete(sent, INFO_TTL))
    return sent


@common_router.message(Command("start"))
async def cmd_start(
    message: Message, db_user: TelegramUser, is_group: bool = False,
) -> None:
    """Xu ly lenh /start - Loi chao va gioi thieu bot."""
    features = FeatureRegistry.get_all()

    feature_list = ""
    if features:
        for name, info in features.items():
            feature_list += f"  • <b>{name}</b> — {info.description}\n"
    else:
        feature_list = "  Chua co tinh nang nao duoc dang ky.\n"

    text = (
        f"Xin chào <b>{message.from_user.first_name or 'bạn'}</b>!\n\n"
        f"<b>X-Bot</b> — các tính năng hiện có:\n"
        f"{feature_list}\n"
        f"Gõ /help để xem danh sách lệnh.\n"
        f"Gõ /features để xem quyền truy cập của bạn."
    )
    await _reply_info(message, text, is_group)


@common_router.message(Command("help"))
async def cmd_help(
    message: Message, db_user: TelegramUser, is_group: bool = False,
) -> None:
    """Xu ly lenh /help - Hien thi danh sach tat ca cac lenh."""
    features = FeatureRegistry.get_all()

    text = "<b>Danh sách lệnh</b>\n\n"
    text += "<b>Chung</b>\n"
    text += "  /start — Khởi động bot\n"
    text += "  /help — Xem danh sách lệnh\n"
    text += "  /id — Xem Telegram ID của bạn\n"
    text += "  /features — Xem quyền truy cập\n\n"

    if features:
        for name, info in features.items():
            text += f"<b>{name}</b> — {info.description}\n"
            for cmd in info.commands:
                text += f"  /{cmd}\n"
            text += "\n"

    await _reply_info(message, text, is_group)


@common_router.message(Command("id"))
async def cmd_id(
    message: Message, db_user: TelegramUser, is_group: bool = False,
) -> None:
    """Xu ly lenh /id - Hien thi Telegram ID cua nguoi dung."""
    text = (
        f"<b>Thông tin của bạn</b>\n\n"
        f"Telegram ID: <code>{message.from_user.id}</code>\n"
        f"Username: @{message.from_user.username or 'N/A'}\n"
        f"Tên: {message.from_user.first_name or 'N/A'}"
    )
    await _reply_info(message, text, is_group)


@common_router.message(Command("features"))
async def cmd_features(
    message: Message, db_user: TelegramUser, is_group: bool = False,
) -> None:
    """Xu ly lenh /features - Hien thi quyen truy cap tinh nang cua nguoi dung."""
    permissions = await get_user_permissions(db_user.id)

    if not permissions:
        await _reply_info(message, "Chưa có tính năng nào được cài đặt.", is_group)
        return

    text = "<b>Quyền truy cập của bạn</b>\n\n"
    for perm in permissions:
        if not perm["feature_enabled"]:
            status = "Tắt (toàn cục)"
        elif perm["allowed"]:
            status = "Được phép"
        else:
            status = "Bị chặn"
        text += f"  • <b>{perm['feature_name']}</b>: {status}\n"

    await _reply_info(message, text, is_group)
