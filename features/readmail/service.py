"""Async service wrapper — boc cac ham sync graph_api thanh async.

MAX_MAIL_WORKERS va TOKEN_EXCHANGE_CONCURRENCY doc tu Admin -> Bot Settings.
Thread pool / semaphore duoc tao LUC DUNG (khong phai luc import) va tu tao lai
khi gia tri trong admin thay doi — khong can restart bot.
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from features.readmail import graph_api
from features.readmail.graph_api import (
    exchange_refresh_token,
    get_message_detail,
    get_messages,
)

logger = logging.getLogger(__name__)

# ── Thread pool tao lazy, tu ap dung cau hinh tu admin ─────────────────────
DEFAULT_MAX_WORKERS = 10
DEFAULT_TOKEN_CONCURRENCY = 4
TUNING_TTL = 30  # giay: khoang cach giua 2 lan doc lai cau hinh tu DB

_executor: ThreadPoolExecutor | None = None
_executor_size = 0
_tuning_checked_at = 0.0


def _clamp(raw, default: int, lo: int, hi: int) -> int:
    """Doi gia tri cau hinh sang int trong khoang [lo, hi]."""
    try:
        return max(lo, min(int(str(raw).strip()), hi))
    except (TypeError, ValueError):
        return default


async def _get_executor() -> ThreadPoolExecutor:
    """Lay thread pool; dinh ky doc lai cau hinh tu admin va ap dung."""
    global _executor, _executor_size, _tuning_checked_at

    now = time.monotonic()
    if _executor is not None and (now - _tuning_checked_at) < TUNING_TTL:
        return _executor
    _tuning_checked_at = now

    workers = DEFAULT_MAX_WORKERS
    token_conc = DEFAULT_TOKEN_CONCURRENCY
    try:
        from core.db import get_setting
        workers = _clamp(
            await get_setting("MAX_MAIL_WORKERS"), DEFAULT_MAX_WORKERS, 1, 100,
        )
        token_conc = _clamp(
            await get_setting("TOKEN_EXCHANGE_CONCURRENCY"),
            DEFAULT_TOKEN_CONCURRENCY, 1, 50,
        )
    except Exception:
        logger.exception("Khong doc duoc cau hinh tu admin, dung mac dinh:")

    # Ap dung so luong dong thoi khi doi token
    graph_api.set_token_concurrency(token_conc)

    # Tao lai thread pool neu chua co hoac so worker thay doi
    if _executor is None or workers != _executor_size:
        old = _executor
        _executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="readmail",
        )
        _executor_size = workers
        if old is not None:
            old.shutdown(wait=False)
            logger.info("MAX_MAIL_WORKERS doi thanh %d", workers)

    return _executor


def _sync_read_mail(account: dict, limit: int = 5) -> dict:
    """Doc mail dong bo cho mot tai khoan."""
    email_addr = account.get("email", "")
    refresh_token = account.get("refresh_token", "")
    client_id = account.get("client_id", "")
    tenant_id = account.get("tenant_id", "consumers")

    if not refresh_token or not client_id:
        return {
            "email": email_addr,
            "status": "error",
            "error": "Thieu refresh_token hoac client_id",
            "data": [],
        }

    # Doi token
    success, token_result = exchange_refresh_token(refresh_token, client_id, tenant_id)
    if not success:
        return {
            "email": email_addr,
            "status": "error",
            "error": f"Doi token that bai: {token_result}",
            "data": [],
        }

    # Doc mail
    success, messages = get_messages(token_result, limit=limit, email_addr=email_addr)
    if not success:
        return {
            "email": email_addr,
            "status": "error",
            "error": f"Doc mail that bai: {messages}",
            "data": [],
        }

    return {
        "email": email_addr,
        "status": "ok",
        "error": None,
        "data": messages,
    }


def _sync_get_code(account: dict, limit: int = 5) -> dict:
    """Tim ma xac nhan tot nhat tu cac email moi nhat."""
    result = _sync_read_mail(account, limit)
    if result["status"] != "ok":
        return result

    # Tim ma tot nhat trong cac email
    for msg in result["data"]:
        if msg.get("code"):
            return {
                "email": result["email"],
                "status": "ok",
                "error": None,
                "data": msg["code"],
                "source_message": {
                    "subject": msg.get("subject", ""),
                    "from": msg.get("from_address", ""),
                    "date": msg.get("date", ""),
                },
            }

    return {
        "email": result["email"],
        "status": "not_found",
        "error": "Khong tim thay ma xac nhan",
        "data": None,
    }


def _sync_get_all_codes(account: dict, limit: int = 5) -> dict:
    """Tim tat ca ma xac nhan tu cac email moi nhat."""
    result = _sync_read_mail(account, limit)
    if result["status"] != "ok":
        return result

    codes = []
    for msg in result["data"]:
        if msg.get("code"):
            codes.append({
                "code": msg["code"],
                "subject": msg.get("subject", ""),
                "from": msg.get("from_address", ""),
                "date": msg.get("date", ""),
            })

    if not codes:
        return {
            "email": result["email"],
            "status": "not_found",
            "error": "Khong tim thay ma xac nhan nao",
            "data": [],
        }

    return {
        "email": result["email"],
        "status": "ok",
        "error": None,
        "data": codes,
    }


def _sync_mail_detail(account: dict, message_id: str) -> dict:
    """Doc chi tiet mot email dong bo."""
    email_addr = account.get("email", "")
    refresh_token = account.get("refresh_token", "")
    client_id = account.get("client_id", "")
    tenant_id = account.get("tenant_id", "consumers")

    if not refresh_token or not client_id:
        return {
            "email": email_addr,
            "status": "error",
            "error": "Thieu refresh_token hoac client_id",
            "data": None,
        }

    # Doi token
    success, token_result = exchange_refresh_token(refresh_token, client_id, tenant_id)
    if not success:
        return {
            "email": email_addr,
            "status": "error",
            "error": f"Doi token that bai: {token_result}",
            "data": None,
        }

    # Doc chi tiet
    success, detail = get_message_detail(
        token_result, message_id, email_addr=email_addr
    )
    if not success:
        return {
            "email": email_addr,
            "status": "error",
            "error": f"Doc chi tiet that bai: {detail}",
            "data": None,
        }

    return {
        "email": email_addr,
        "status": "ok",
        "error": None,
        "data": detail,
    }


async def async_read_mail(account: dict, limit: int = 5) -> dict:
    """Doc mail async cho mot tai khoan."""
    loop = asyncio.get_running_loop()
    ex = await _get_executor()
    return await loop.run_in_executor(ex, _sync_read_mail, account, limit)


async def async_read_all_accounts(
    accounts: list[dict], limit: int = 1
) -> list[dict]:
    """Doc mail tat ca tai khoan song song."""
    tasks = [async_read_mail(acc, limit) for acc in accounts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    final_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            email_addr = accounts[i].get("email", f"Account {i}")
            final_results.append({
                "email": email_addr,
                "status": "error",
                "error": str(result),
                "data": [],
            })
        else:
            final_results.append(result)

    return final_results


async def async_get_code(account: dict, limit: int = 5) -> dict:
    """Tim ma xac nhan tot nhat async."""
    loop = asyncio.get_running_loop()
    ex = await _get_executor()
    return await loop.run_in_executor(ex, _sync_get_code, account, limit)


async def async_get_all_codes(account: dict, limit: int = 5) -> dict:
    """Tim tat ca ma xac nhan async."""
    loop = asyncio.get_running_loop()
    ex = await _get_executor()
    return await loop.run_in_executor(ex, _sync_get_all_codes, account, limit)


async def async_mail_detail(account: dict, message_id: str) -> dict:
    """Doc chi tiet mot email async."""
    loop = asyncio.get_running_loop()
    ex = await _get_executor()
    return await loop.run_in_executor(
        ex, _sync_mail_detail, account, message_id
    )
