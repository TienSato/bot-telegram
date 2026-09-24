"""
Read Mail Bot — Main entry point.

Chay dong thoi:
  1. Django admin panel (uvicorn ASGI)
  2. BotManager — tu dong quan ly cac bot Telegram

BotManager tu dong:
  - Phat hien bot moi duoc them qua admin panel
  - Dung bot bi vo hieu hoa
  - Khoi dong lai bot khi thay doi token hoac chuc nang
  - KHONG CAN restart container
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field

# ── Khoi tao Django truoc ───────────────────────────────────────────────────
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")

import django  # noqa: E402
django.setup()

# Gio co the import cac module phu thuoc Django
import uvicorn  # noqa: E402
from django.conf import settings  # noqa: E402

from bot.bot import setup_bot  # noqa: E402
from core.db import (  # noqa: E402
    get_active_bots,
    get_bot_feature_names,
    init_default_features,
    init_default_settings,
)

# Nap cac tinh nang (moi tinh nang = 1 thu muc trong features/).
# Import THANG module handlers de dam bao router duoc dang ky du __init__.py
# co ton tai hay khong. Them tinh nang moi: them 1 dong import handlers o day.
from features.registry import FeatureRegistry  # noqa: E402
import features.readmail.handlers  # noqa: F401, E402  # tinh nang: doc mail Hotmail/Outlook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Khoang thoi gian kiem tra thay doi bot (giay) ──────────────────────────
BOT_CHECK_INTERVAL = int(os.getenv("BOT_CHECK_INTERVAL", "10"))


# ── BotInstance ────────────────────────────────────────────────────────────


@dataclass
class BotInstance:
    """Thong tin mot bot dang chay."""

    task: asyncio.Task
    bot: object  # aiogram.Bot
    dp: object   # aiogram.Dispatcher
    token: str
    features: frozenset[str]
    name: str


# ── BotManager ─────────────────────────────────────────────────────────────


class BotManager:
    """
    Quan ly lifecycle cac bot Telegram.

    Tu dong phat hien thay doi trong database (qua admin panel)
    va start/stop/restart bot tuong ung ma khong can restart container.
    """

    def __init__(self, check_interval: int = BOT_CHECK_INTERVAL) -> None:
        self._running: dict[int, BotInstance] = {}
        self._check_interval = check_interval

    @property
    def running_count(self) -> int:
        return len(self._running)

    async def run(self) -> None:
        """Vong lap chinh — kiem tra thay doi dinh ky."""
        logger.info(
            "BotManager khoi dong — kiem tra thay doi moi %ds",
            self._check_interval,
        )
        # Dong bo lan dau
        await self._sync_bots()

        while True:
            await asyncio.sleep(self._check_interval)
            try:
                await self._sync_bots()
            except Exception:
                logger.exception("BotManager: loi khi dong bo bot")

    async def _sync_bots(self) -> None:
        """So sanh trang thai DB voi cac bot dang chay, cap nhat."""
        # Lay danh sach bot dang hoat dong tu DB
        db_bots = await get_active_bots()
        db_bot_map: dict[int, object] = {b.id: b for b in db_bots}

        # --- Dung cac bot khong con trong DB hoac da bi tat ---
        for bot_id in list(self._running):
            if bot_id not in db_bot_map:
                logger.info(
                    "BotManager: bot ID=%d da bi xoa/tat — dang dung...",
                    bot_id,
                )
                await self._stop_bot(bot_id)

        # --- Start hoac restart cac bot ---
        for db_bot in db_bots:
            features = frozenset(await get_bot_feature_names(db_bot.id))
            running = self._running.get(db_bot.id)

            if running is None:
                # Bot moi — khoi dong
                await self._start_bot(db_bot, features)

            elif running.token != db_bot.token or running.features != features:
                # Token hoac chuc nang thay doi — restart
                reason = []
                if running.token != db_bot.token:
                    reason.append("token")
                if running.features != features:
                    reason.append("chuc nang")
                logger.info(
                    "BotManager: bot [%s] thay doi %s — dang restart...",
                    db_bot.name,
                    ", ".join(reason),
                )
                await self._stop_bot(db_bot.id)
                await self._start_bot(db_bot, features)

    async def _start_bot(
        self, db_bot: object, features: frozenset[str],
    ) -> None:
        """Khoi dong mot bot moi."""
        try:
            bot, dp = setup_bot(
                token=db_bot.token,
                feature_names=list(features) if features else None,
                bot_name=db_bot.name,
            )
        except Exception:
            logger.exception(
                "BotManager: khong the khoi tao bot [%s]", db_bot.name,
            )
            return

        task = asyncio.create_task(
            self._run_polling(bot, dp, db_bot.name, db_bot.id),
        )
        self._running[db_bot.id] = BotInstance(
            task=task,
            bot=bot,
            dp=dp,
            token=db_bot.token,
            features=features,
            name=db_bot.name,
        )
        logger.info("BotManager: da khoi dong bot [%s]", db_bot.name)

    async def _stop_bot(self, bot_id: int) -> None:
        """Dung mot bot dang chay."""
        instance = self._running.pop(bot_id, None)
        if instance is None:
            return

        try:
            # Dung polling truoc
            await instance.dp.stop_polling()
        except Exception:
            logger.debug("stop_polling exception for [%s]", instance.name)

        # Huy task
        instance.task.cancel()
        try:
            await instance.task
        except (asyncio.CancelledError, Exception):
            pass

        # Dong session HTTP cua bot
        try:
            await instance.bot.session.close()
        except Exception:
            pass

        logger.info("BotManager: da dung bot [%s]", instance.name)

    async def _run_polling(
        self, bot: object, dp: object, name: str, bot_id: int,
    ) -> None:
        """Chay polling cho mot bot. Log loi neu bi crash."""
        try:
            logger.info("Bot [%s] bat dau polling...", name)
            await dp.start_polling(bot)
        except asyncio.CancelledError:
            logger.debug("Bot [%s] polling bi cancel.", name)
        except Exception:
            logger.exception("Bot [%s] gap loi khi polling:", name)
            # Xoa khoi danh sach running de sync tiep tuc retry
            self._running.pop(bot_id, None)
        finally:
            logger.info("Bot [%s] da dung polling.", name)

    async def stop_all(self) -> None:
        """Dung tat ca bot dang chay."""
        for bot_id in list(self._running):
            await self._stop_bot(bot_id)
        logger.info("BotManager: da dung tat ca bot.")


# ── Admin panel ────────────────────────────────────────────────────────────


async def run_admin_panel() -> None:
    """Chay trang quan tri Django qua uvicorn."""
    config = uvicorn.Config(
        app="web.asgi:application",
        host="0.0.0.0",
        port=settings.ADMIN_PORT,
        log_level="info",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    await server.serve()


# ── Khoi tao database ─────────────────────────────────────────────────────


async def init_db() -> None:
    """Khoi tao du lieu mac dinh trong database."""
    await init_default_features(FeatureRegistry.get_all())
    await init_default_settings()
    logger.info("Da khoi tao du lieu mac dinh trong database.")


# ── Main ───────────────────────────────────────────────────────────────────


async def main() -> None:
    """Ham chinh — khoi dong admin panel va BotManager."""
    # Khoi tao du lieu mac dinh
    await init_db()

    # Tao BotManager
    bot_manager = BotManager(check_interval=BOT_CHECK_INTERVAL)

    # Chay trang quan tri — luon chay
    admin_task = asyncio.create_task(run_admin_panel())
    logger.info(
        "Trang quan tri dang chay tai http://0.0.0.0:%s/admin/",
        settings.ADMIN_PORT,
    )

    # Chay BotManager — tu dong quan ly cac bot
    manager_task = asyncio.create_task(bot_manager.run())
    logger.info(
        "BotManager dang chay — tu dong phat hien bot moi/thay doi "
        "(kiem tra moi %ds)",
        BOT_CHECK_INTERVAL,
    )

    # Doi ket thuc
    try:
        done, pending = await asyncio.wait(
            [admin_task, manager_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Cleanup
        await bot_manager.stop_all()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except asyncio.CancelledError:
        await bot_manager.stop_all()

    logger.info("He thong da dung.")


if __name__ == "__main__":
    asyncio.run(main())
