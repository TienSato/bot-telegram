"""Khoi tao Bot va Dispatcher.

Ho tro multi-bot: moi bot chi load cac chuc nang duoc gan cho no.
Ho tro ca private chat va nhom Telegram.
"""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.common import common_router
from bot.middlewares import AuthMiddleware, CommandCleanupMiddleware
from features.registry import FeatureRegistry

logger = logging.getLogger(__name__)


def _include(dp: Dispatcher, router) -> None:
    """Gan router vao Dispatcher, cho phep gan lai khi bot restart (hot-reload).

    Cac router (common_router, feature routers) la singleton cap module. Aiogram
    khong cho mot router gan vao 2 Dispatcher. Khi BotManager restart bot (tao
    Dispatcher moi), ta go router khoi Dispatcher cu (da bo) truoc khi gan lai.
    """
    try:
        router._parent_router = None
    except Exception:
        pass
    dp.include_router(router)


def setup_bot(
    token: str,
    feature_names: list[str] | None = None,
    bot_name: str = "",
) -> tuple[Bot, Dispatcher]:
    """
    Khoi tao Bot va Dispatcher.

    Args:
        token: Bot token tu @BotFather
        feature_names: Danh sach chuc nang duoc gan cho bot nay.
                       None = load tat ca chuc nang.
        bot_name: Ten bot (de hien thi trong log)

    Returns:
        Tuple (Bot, Dispatcher) da duoc cau hinh day du.

    Ho tro:
        - Private chat: phan hoi truc tiep
        - Group chat: phan hoi lenh va callback query
    """
    if not token:
        raise ValueError("Chua cau hinh token cho bot.")

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Middleware xac thuc — ho tro ca message va callback
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # Tu xoa tin nhan lenh (/...) cua user cho gon chat (chay ngoai cung)
    dp.message.outer_middleware(CommandCleanupMiddleware())

    # Dang ky router cac lenh chung (/start, /help, ...)
    _include(dp, common_router)

    # Dang ky router cac chuc nang — chi load nhung chuc nang duoc gan
    all_features = FeatureRegistry.get_all()
    loaded = []
    for name, info in all_features.items():
        if feature_names is None or name in feature_names:
            _include(dp, info.router)
            loaded.append(name)

    label = bot_name or token[:8] + "..."
    if loaded:
        logger.info("Bot [%s] — chức năng: %s", label, ", ".join(loaded))
    else:
        logger.warning("Bot [%s] — chưa gán chức năng nào!", label)

    return bot, dp
