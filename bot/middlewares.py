"""Aiogram middlewares — xac thuc va kiem tra quyen.

Su dung Django async ORM qua core.db thay vi SQLAlchemy.
Ho tro ca tin nhan rieng va nhom.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from core.db import get_or_create_user, get_user_permission, update_last_active

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """
    Middleware xac thuc nguoi dung.
    - Tao hoac lay nguoi dung tu database
    - Cap nhat thoi gian hoat dong
    - Chan nguoi dung bi cam
    - Truyen doi tuong user vao handler qua data["db_user"]
    - Truyen thong tin chat: data["chat_type"], data["chat_id"], data["is_group"]
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Lay thong tin nguoi dung va chat tu event
        user = None
        chat = None

        if isinstance(event, Message):
            user = event.from_user
            chat = event.chat
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            if event.message:
                chat = event.message.chat

        if user is None:
            return await handler(event, data)

        # Truyen thong tin chat vao handler
        if chat:
            chat_type = chat.type  # "private", "group", "supergroup", "channel"
            data["chat_type"] = chat_type
            data["chat_id"] = chat.id
            data["is_group"] = chat_type in ("group", "supergroup")
        else:
            data["chat_type"] = "private"
            data["chat_id"] = None
            data["is_group"] = False

        # Lay hoac tao nguoi dung trong database
        db_user = await get_or_create_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
        )

        # Cap nhat thoi gian hoat dong
        await update_last_active(db_user)

        # Kiem tra nguoi dung bi chan
        if db_user.is_banned:
            if isinstance(event, Message):
                # Trong nhom chi tra loi rieng (reply), trong private tra loi binh thuong
                if data["is_group"]:
                    # Khong phan hoi trong nhom de tranh spam
                    return None
                await event.answer("Bạn đã bị chặn.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Bạn đã bị chặn.", show_alert=True)
            return None

        # Truyen doi tuong user vao handler
        data["db_user"] = db_user

        return await handler(event, data)


class CommandCleanupMiddleware(BaseMiddleware):
    """Sau khi xu ly xong, tu xoa tin nhan LENH (bat dau bang '/') cua user.

    Giup chat nhom gon gang. Chat rieng: bot xoa duoc; nhom: can bot la admin
    co quyen xoa tin (neu khong, bo qua lang le).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        try:
            if (
                isinstance(event, Message)
                and event.text
                and event.text.lstrip().startswith("/")
            ):
                await event.delete()
        except Exception:
            pass
        return result


class FeatureMiddleware(BaseMiddleware):
    """
    Middleware kiem tra quyen truy cap tinh nang.
    Ap dung cho tung router cua tinh nang cu the.
    Ho tro ca private chat va nhom.
    """

    def __init__(self, feature_name: str) -> None:
        super().__init__()
        self.feature_name = feature_name

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db_user = data.get("db_user")

        if db_user is None:
            return await handler(event, data)

        allowed = await get_user_permission(
            user_id=db_user.id,
            feature_name=self.feature_name,
        )

        if not allowed:
            is_group = data.get("is_group", False)

            if isinstance(event, Message):
                if is_group:
                    # Trong nhom: khong phan hoi de tranh spam
                    return None
                await event.answer(
                    "Bạn không có quyền sử dụng chức năng này."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "Bạn không có quyền sử dụng chức năng này.",
                    show_alert=True,
                )
            return None

        return await handler(event, data)
