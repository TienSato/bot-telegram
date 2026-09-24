"""Microsoft Graph API service — doc mail Hotmail/Outlook."""
from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from http.cookiejar import CookiePolicy

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from features.readmail import code_extractor
from features.readmail.imap_reader import read_messages_imap, read_message_detail_imap

logger = logging.getLogger(__name__)

# ── Cau hinh ────────────────────────────────────────────────────────────
TOKEN_EXCHANGE_CONCURRENCY = int(os.getenv("TOKEN_EXCHANGE_CONCURRENCY", "4"))
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0/me"
OUTLOOK_BASE = "https://outlook.office.com/api/v2.0/me"

# Loi co the thu lai
RETRYABLE_ERROR_CODES = {"900144", "900023", "429", "503", "504", "request_error"}
MAX_TOKEN_RETRIES = 2

# Circuit breaker — khoa doi token khi gap AADSTS50196
CIRCUIT_BREAKER_DURATION = 90  # giay

# Tenant hop le
VALID_TENANTS = {"consumers", "common", "organizations"}
GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# ── Cookie policy chan tat ca cookie ─────────────────────────────────────
class BlockAllCookies(CookiePolicy):
    """Chan tat ca cookie — tranh Microsoft tracking."""

    return_ok = (
        lambda self, cookie, request: False
    )
    set_ok = (
        lambda self, cookie, request: False
    )
    domain_return_ok = (
        lambda self, domain, request: False
    )
    path_return_ok = (
        lambda self, path, request: False
    )
    netscape = True
    rfc2965 = False
    hide_cookie2 = False


# ── Session HTTP voi connection pooling ──────────────────────────────────
def _create_session() -> requests.Session:
    """Tao HTTP session voi retry va connection pooling."""
    session = requests.Session()
    session.trust_env = False
    session.cookies.set_policy(BlockAllCookies())

    # Retry chi cho GET, khong retry POST
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=50,
        pool_maxsize=100,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Header gia lap trinh duyet
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    })

    return session


_session = _create_session()

# ── Token cache va concurrency control ───────────────────────────────────
_token_cache: dict[tuple[str, str], tuple[dict, float]] = {}
_token_cache_lock = threading.Lock()
_token_semaphore = threading.Semaphore(TOKEN_EXCHANGE_CONCURRENCY)
_token_semaphore_lock = threading.Lock()


def set_token_concurrency(n: int) -> None:
    """Dat lai so luong doi token dong thoi (goi tu service khi admin doi cau hinh).

    Cac luot doi token dang chay van dung semaphore cu cho den khi xong;
    cac luot moi dung gia tri moi.
    """
    global _token_semaphore, TOKEN_EXCHANGE_CONCURRENCY
    if n < 1 or n == TOKEN_EXCHANGE_CONCURRENCY:
        return
    with _token_semaphore_lock:
        TOKEN_EXCHANGE_CONCURRENCY = n
        _token_semaphore = threading.Semaphore(n)
    logger.info("TOKEN_EXCHANGE_CONCURRENCY doi thanh %d", n)


# Circuit breaker state
_circuit_breaker_until: float = 0.0
_circuit_breaker_lock = threading.Lock()


# ── Helpers ──────────────────────────────────────────────────────────────
def _sanitize_tenant_id(tenant_id: str) -> str:
    """Kiem tra va lam sach tenant_id."""
    if not tenant_id:
        return "consumers"
    tenant_id = tenant_id.strip()
    if tenant_id.lower() in VALID_TENANTS:
        return tenant_id.lower()
    if GUID_PATTERN.match(tenant_id):
        return tenant_id
    logger.warning("Tenant ID khong hop le: %s, su dung 'consumers'", tenant_id)
    return "consumers"


def _is_circuit_open() -> bool:
    """Kiem tra circuit breaker co dang mo khong."""
    with _circuit_breaker_lock:
        return time.time() < _circuit_breaker_until


def _trip_circuit_breaker() -> None:
    """Kich hoat circuit breaker."""
    with _circuit_breaker_lock:
        global _circuit_breaker_until
        _circuit_breaker_until = time.time() + CIRCUIT_BREAKER_DURATION
        logger.warning(
            "Circuit breaker kich hoat — khoa doi token %ds", CIRCUIT_BREAKER_DURATION
        )


def _get_cached_token(
    refresh_token: str, client_id: str
) -> dict | None:
    """Lay token tu cache neu con han."""
    key = (refresh_token, client_id)
    with _token_cache_lock:
        if key in _token_cache:
            token_info, expire_at = _token_cache[key]
            # Con han it nhat 120 giay
            if time.time() < expire_at - 120:
                return token_info
            else:
                del _token_cache[key]
    return None


def _set_cached_token(
    refresh_token: str, client_id: str, token_info: dict
) -> None:
    """Luu token vao cache."""
    key = (refresh_token, client_id)
    expires_in = token_info.get("expires_in", 3600)
    expire_at = time.time() + expires_in
    with _token_cache_lock:
        _token_cache[key] = (token_info, expire_at)


def _do_token_exchange(
    refresh_token: str,
    client_id: str,
    tenant_id: str,
    scope: str | None = None,
) -> tuple[bool, dict | str]:
    """Thuc hien doi refresh token lay access token."""
    url = TOKEN_URL.format(tenant=tenant_id)
    data = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if scope:
        data["scope"] = scope

    try:
        resp = _session.post(url, data=data, timeout=30)
    except requests.RequestException as e:
        return False, f"request_error: {str(e)}"

    if resp.status_code == 200:
        token_data = resp.json()
        return True, token_data

    # Xu ly loi
    try:
        error_data = resp.json()
        error_code = str(error_data.get("error_codes", [0])[0])
        error_desc = error_data.get("error_description", "")
    except Exception:
        error_code = str(resp.status_code)
        error_desc = resp.text[:500]

    # AADSTS50196 — kich hoat circuit breaker
    if "AADSTS50196" in error_desc or "50196" in error_code:
        _trip_circuit_breaker()
        return False, f"AADSTS50196: {error_desc[:200]}"

    return False, f"error_{error_code}: {error_desc[:300]}"


def _is_retryable_error(error_str: str) -> bool:
    """Kiem tra loi co the thu lai khong."""
    for code in RETRYABLE_ERROR_CODES:
        if code in error_str:
            return True
    return False


def _has_mail_scope(token_info: dict) -> str | None:
    """
    Kiem tra token co scope doc mail khong.

    Returns "graph" neu co scope Graph, "outlook" neu co scope Outlook, None neu khong co.
    """
    scope = token_info.get("scope", "")
    scope_lower = scope.lower()
    if "mail.read" in scope_lower:
        if "graph" in scope_lower or "https://graph.microsoft.com" in scope_lower:
            return "graph"
        if "outlook" in scope_lower or "https://outlook.office.com" in scope_lower:
            return "outlook"
        # Mac dinh la Graph
        return "graph"
    return None


# ── API chinh ────────────────────────────────────────────────────────────
def exchange_refresh_token(
    refresh_token: str,
    client_id: str,
    tenant_id: str = "consumers",
) -> tuple[bool, dict | str]:
    """
    Doi refresh token lay access token.

    Chien luoc:
    1. Kiem tra cache -> tra ve neu con han
    2. Kiem tra circuit breaker -> loi neu dang mo
    3. Doi khong co scope (duong nhanh)
    4. Neu token khong co mail scope -> thu Graph Mail.Read, roi Outlook Mail.Read
    5. Neu tat ca that bai -> tra ve loi

    Returns (success, token_info_dict | error_string).
    """
    tenant_id = _sanitize_tenant_id(tenant_id)

    # Buoc 1: Kiem tra cache
    cached = _get_cached_token(refresh_token, client_id)
    if cached:
        return True, cached

    # Buoc 2: Kiem tra circuit breaker
    if _is_circuit_open():
        return False, "Circuit breaker dang mo — thu lai sau"

    # Jitter truoc khi doi token
    time.sleep(random.uniform(0.05, 0.3))

    with _token_semaphore:
        # Kiem tra cache lan nua (co the da duoc cap nhat boi thread khac)
        cached = _get_cached_token(refresh_token, client_id)
        if cached:
            return True, cached

        last_error = ""

        for attempt in range(MAX_TOKEN_RETRIES + 1):
            if attempt > 0:
                backoff = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(backoff)

            # Buoc 3: Doi khong co scope (duong nhanh)
            success, result = _do_token_exchange(
                refresh_token, client_id, tenant_id, scope=None
            )
            if success:
                # Kiem tra co mail scope khong
                mail_api = _has_mail_scope(result)
                if mail_api:
                    _set_cached_token(refresh_token, client_id, result)
                    return True, result

                # Buoc 4: Thu voi Graph Mail.Read scope
                success_graph, result_graph = _do_token_exchange(
                    refresh_token, client_id, tenant_id,
                    scope="https://graph.microsoft.com/Mail.Read offline_access",
                )
                if success_graph:
                    _set_cached_token(refresh_token, client_id, result_graph)
                    return True, result_graph

                # Thu voi Outlook Mail.Read scope
                success_outlook, result_outlook = _do_token_exchange(
                    refresh_token, client_id, tenant_id,
                    scope="https://outlook.office.com/Mail.Read offline_access",
                )
                if success_outlook:
                    _set_cached_token(refresh_token, client_id, result_outlook)
                    return True, result_outlook

                # Neu khong duoc scope nao, van luu token khong scope de dung fallback
                _set_cached_token(refresh_token, client_id, result)
                return True, result

            # Doi that bai — kiem tra co retryable khong
            last_error = result if isinstance(result, str) else str(result)
            if not _is_retryable_error(last_error):
                break

        return False, last_error


def _format_message(msg_data: dict, api_type: str = "graph") -> dict:
    """Chuan hoa du lieu message tu Graph/Outlook API."""
    if api_type == "graph":
        from_info = msg_data.get("from", {}).get("emailAddress", {})
        subject = msg_data.get("subject", "(Khong co tieu de)")
        snippet = msg_data.get("bodyPreview", "")
        from_name = from_info.get("name", "")
        from_address = from_info.get("address", "")
        date = msg_data.get("receivedDateTime", "")
        msg_id = msg_data.get("id", "")
    else:
        # Outlook API format
        from_info = msg_data.get("From", {}).get("EmailAddress", {})
        subject = msg_data.get("Subject", "(Khong co tieu de)")
        snippet = msg_data.get("BodyPreview", "")
        from_name = from_info.get("Name", "")
        from_address = from_info.get("Address", "")
        date = msg_data.get("DateTimeReceived", msg_data.get("ReceivedDateTime", ""))
        msg_id = msg_data.get("Id", "")

    # Tim ma xac nhan
    code_info = code_extractor.find_best_code(subject, snippet, from_address)

    return {
        "id": msg_id,
        "subject": subject,
        "from_name": from_name,
        "from_address": from_address,
        "date": date,
        "snippet": snippet,
        "code": code_info,
    }


def _format_message_detail(msg_data: dict, api_type: str = "graph") -> dict:
    """Chuan hoa du lieu chi tiet message."""
    base = _format_message(msg_data, api_type)

    if api_type == "graph":
        body = msg_data.get("body", {})
        html_body = body.get("content", "")
        content_type = body.get("contentType", "text").lower()
    else:
        body = msg_data.get("Body", {})
        html_body = body.get("Content", "")
        content_type = body.get("ContentType", "Text").lower()

    base["html_body"] = html_body
    base["content_type"] = content_type

    return base


def _fetch_graph_messages(
    token_info: dict, limit: int, email_addr: str
) -> tuple[bool, list[dict] | str]:
    """Lay danh sach message tu Graph API."""
    access_token = token_info.get("access_token", "")
    url = f"{GRAPH_BASE}/messages"
    params = {
        "$top": limit,
        "$select": "id,subject,from,bodyPreview,receivedDateTime",
        "$orderby": "receivedDateTime desc",
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        resp = _session.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as e:
        return False, f"Graph request error: {str(e)}"

    if resp.status_code == 200:
        data = resp.json()
        messages = [
            _format_message(m, "graph") for m in data.get("value", [])
        ]
        return True, messages

    return False, f"Graph API error {resp.status_code}: {resp.text[:300]}"


def _fetch_outlook_messages(
    token_info: dict, limit: int, email_addr: str
) -> tuple[bool, list[dict] | str]:
    """Lay danh sach message tu Outlook REST API."""
    access_token = token_info.get("access_token", "")
    url = f"{OUTLOOK_BASE}/messages"
    params = {
        "$top": limit,
        "$select": "Id,Subject,From,BodyPreview,DateTimeReceived",
        "$orderby": "DateTimeReceived desc",
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        resp = _session.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as e:
        return False, f"Outlook request error: {str(e)}"

    if resp.status_code == 200:
        data = resp.json()
        messages = [
            _format_message(m, "outlook") for m in data.get("value", [])
        ]
        return True, messages

    return False, f"Outlook API error {resp.status_code}: {resp.text[:300]}"


def _fetch_graph_message_detail(
    token_info: dict, message_id: str, email_addr: str
) -> tuple[bool, dict | str]:
    """Lay chi tiet message tu Graph API."""
    access_token = token_info.get("access_token", "")
    url = f"{GRAPH_BASE}/messages/{message_id}"
    params = {
        "$select": "id,subject,from,bodyPreview,receivedDateTime,body",
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        resp = _session.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as e:
        return False, f"Graph request error: {str(e)}"

    if resp.status_code == 200:
        return True, _format_message_detail(resp.json(), "graph")

    return False, f"Graph API error {resp.status_code}: {resp.text[:300]}"


def _fetch_outlook_message_detail(
    token_info: dict, message_id: str, email_addr: str
) -> tuple[bool, dict | str]:
    """Lay chi tiet message tu Outlook REST API."""
    access_token = token_info.get("access_token", "")
    url = f"{OUTLOOK_BASE}/messages/{message_id}"
    params = {
        "$select": "Id,Subject,From,BodyPreview,DateTimeReceived,Body",
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        resp = _session.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as e:
        return False, f"Outlook request error: {str(e)}"

    if resp.status_code == 200:
        return True, _format_message_detail(resp.json(), "outlook")

    return False, f"Outlook API error {resp.status_code}: {resp.text[:300]}"


def get_messages(
    token_info: dict, limit: int = 10, email_addr: str = ""
) -> tuple[bool, list[dict] | str]:
    """
    Lay danh sach email moi nhat.

    Chien luoc:
    1. Thu API uu tien (graph hoac outlook tuy theo scope)
    2. Fallback sang API con lai
    3. Fallback sang IMAP XOAUTH2

    Returns (success, messages_list | error_string).
    """
    access_token = token_info.get("access_token", "")
    mail_api = _has_mail_scope(token_info)

    # Xac dinh thu tu API
    if mail_api == "outlook":
        primary_fetch = _fetch_outlook_messages
        fallback_fetch = _fetch_graph_messages
    else:
        primary_fetch = _fetch_graph_messages
        fallback_fetch = _fetch_outlook_messages

    # Thu API uu tien
    success, result = primary_fetch(token_info, limit, email_addr)
    if success:
        return True, result

    logger.info("API uu tien that bai, thu fallback: %s", result)

    # Thu fallback API
    success, result = fallback_fetch(token_info, limit, email_addr)
    if success:
        return True, result

    logger.info("Fallback API that bai, thu IMAP: %s", result)

    # Fallback sang IMAP
    if email_addr:
        success, result = read_messages_imap(access_token, email_addr, limit)
        if success:
            return True, result
        logger.warning("IMAP fallback that bai: %s", result)

    return False, f"Tat ca phuong thuc doc mail that bai. Loi cuoi: {result}"


def get_message_detail(
    token_info: dict, message_id: str, email_addr: str = ""
) -> tuple[bool, dict | str]:
    """
    Lay chi tiet mot email.

    Returns (success, detail_dict | error_string).
    """
    access_token = token_info.get("access_token", "")

    # Neu la IMAP message
    if message_id.startswith("imap_"):
        if email_addr:
            return read_message_detail_imap(access_token, email_addr, message_id)
        return False, "Can email address de doc IMAP message"

    mail_api = _has_mail_scope(token_info)

    if mail_api == "outlook":
        primary_fetch = _fetch_outlook_message_detail
        fallback_fetch = _fetch_graph_message_detail
    else:
        primary_fetch = _fetch_graph_message_detail
        fallback_fetch = _fetch_outlook_message_detail

    # Thu API uu tien
    success, result = primary_fetch(token_info, message_id, email_addr)
    if success:
        return True, result

    logger.info("API chi tiet uu tien that bai, thu fallback: %s", result)

    # Thu fallback
    success, result = fallback_fetch(token_info, message_id, email_addr)
    if success:
        return True, result

    return False, f"Khong the doc chi tiet email: {result}"
