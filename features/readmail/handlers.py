"""Aiogram handlers — cac lenh Telegram cho ReadMail feature.

Su dung Django async ORM qua core.db thay vi SQLAlchemy.
Khong can async with get_session(), khong can session.commit().

Ho tro 2 cach dung:
  1. Lenh text: /addmail, /mail, /code, ...
  2. Menu nut bam: /them -> gui mail -> hien menu chuc nang (Doc mail, Lay code...)
"""
from __future__ import annotations

import html
import io
import logging
import os
import re
import unicodedata

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from bot.middlewares import FeatureMiddleware
from features.readmail.service import (
    async_get_all_codes,
    async_get_code,
    async_mail_detail,
    async_read_all_accounts,
    async_read_mail,
)

logger = logging.getLogger(__name__)

FEATURE_NAME = "readmail"
FEATURE_DESC = "Doc mail Hotmail/Outlook"
FEATURE_COMMANDS = [
    "them", "menu",
    "addmail", "listmail", "delmail", "mail",
    "readall", "code", "codes", "maildetail",
]

router = Router(name=FEATURE_NAME)

# Gan FeatureMiddleware -> kiem tra quyen user (ma tran quyen trong admin)
router.message.middleware(FeatureMiddleware(FEATURE_NAME))
router.callback_query.middleware(FeatureMiddleware(FEATURE_NAME))

# ── Gioi han ky tu Telegram ──────────────────────────────────────────────
MAX_MSG_LEN = 4000

# ── Chuan hoa dau vao ────────────────────────────────────────────────────
# Bo cac ky tu zero-width / dieu khien huong (lam hong parse combo)
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
# Kich thuoc toi da file .txt nhan qua Telegram
_MAX_TXT_BYTES = 2 * 1024 * 1024


def _normalize_input(text: str) -> str:
    """Chuan hoa dau vao truoc khi parse combo.

    Nhieu nguoi copy combo bi dinh dinh dang "chu nghieng"/"chu dam" kieu
    Unicode (Mathematical Alphanumeric Symbols) hoac ky tu full-width. NFKC
    dua tat ca ve chu/so ASCII binh thuong (ca dau '|' full-width). Dong thoi
    bo cac ky tu zero-width vo hinh khien tach truong sai.
    """
    if not text:
        return text
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    return text

# ── Cache danh sach mail da doc (de xem chi tiet qua nut bam) ─────────────
# Key: (telegram_user_db_id, account_id) -> list[message_dict]
_mail_cache: dict[tuple[int, int], list[dict]] = {}


# ── FSM States cho /addmail ──────────────────────────────────────────────
class AddMailStates(StatesGroup):
    waiting_for_credentials = State()


# ── FSM States cho ghi chu tai khoan ─────────────────────────────────────
class NoteStates(StatesGroup):
    waiting_for_note = State()


# ── Helper functions ─────────────────────────────────────────────────────
def _split_message(text: str, max_len: int = MAX_MSG_LEN) -> list[str]:
    """Chia message dai thanh nhieu phan."""
    if len(text) <= max_len:
        return [text]

    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        # Tim vi tri xuong dong gan nhat truoc max_len
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos == -1:
            split_pos = max_len
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return parts


def _account_to_dict(acc) -> dict:
    """Chuyen doi MailAccount object sang dict cho service layer."""
    return {
        "email": acc.email,
        "refresh_token": acc.refresh_token,
        "client_id": acc.client_id,
        "tenant_id": acc.tenant_id or "consumers",
    }


def _format_mail_list(
    messages: list[dict], email_addr: str = "", start: int = 1,
) -> str:
    """Format danh sach email thanh text HTML. So thu tu bat dau tu `start`."""
    if not messages:
        return f"<b>{html.escape(email_addr)}</b>\nKhong co email nao."

    lines = [f"<b>{html.escape(email_addr)}</b>\n"]
    for i, msg in enumerate(messages, start):
        subject = html.escape(msg.get("subject", "(Khong co tieu de)"))
        from_name = html.escape(msg.get("from_name", ""))
        from_addr = html.escape(msg.get("from_address", ""))
        date = html.escape(msg.get("date", "")[:16])
        snippet = html.escape(msg.get("snippet", "")[:100])

        lines.append(f"<b>{i}.</b> {subject}")
        lines.append(f"   {from_name} &lt;{from_addr}&gt;")
        lines.append(f"   {date}")

        if snippet:
            lines.append(f"   {snippet}")

        code_info = msg.get("code")
        if code_info:
            code_val = html.escape(str(code_info.get("value", "")))
            lines.append(f"   <b>Code: {code_val}</b>")

        lines.append("")

    return "\n".join(lines)


def _format_code_result(result: dict) -> str:
    """Format ket qua tim code thanh text HTML."""
    email_addr = html.escape(result.get("email", ""))
    status = result.get("status", "")

    if status == "error":
        error = html.escape(result.get("error", "Loi khong xac dinh"))
        return f"<b>{email_addr}</b>\n{error}"

    if status == "not_found":
        return f"<b>{email_addr}</b>\nKhong tim thay ma xac nhan."

    data = result.get("data")
    if not data:
        return f"<b>{email_addr}</b>\nKhong co du lieu."

    # Ket qua code don (async_get_code)
    if isinstance(data, dict) and data.get("type") == "code":
        code_val = html.escape(str(data.get("value", "")))
        context = html.escape(str(data.get("context", ""))[:80])
        source = result.get("source_message", {})
        subject = html.escape(source.get("subject", "")[:80])
        from_addr = html.escape(source.get("from", ""))

        lines = [
            f"<b>{email_addr}</b>",
            f"   Ma: <b><code>{code_val}</code></b>",
        ]
        if context:
            lines.append(f"   Ngu canh: {context}")
        if subject:
            lines.append(f"   Tu email: {subject}")
        if from_addr:
            lines.append(f"   Nguoi gui: {from_addr}")

        return "\n".join(lines)

    # Danh sach codes (async_get_all_codes)
    if isinstance(data, list):
        lines = [f"<b>{email_addr}</b> — {len(data)} ma tim thay:\n"]
        for i, item in enumerate(data, 1):
            code_info = item.get("code", {})
            code_val = html.escape(str(code_info.get("value", "")))
            subject = html.escape(item.get("subject", "")[:60])
            from_addr = html.escape(item.get("from", ""))
            lines.append(f"  <b>{i}.</b> <code>{code_val}</code>")
            if subject:
                lines.append(f"     {subject}")
            if from_addr:
                lines.append(f"     {from_addr}")
            lines.append("")
        return "\n".join(lines)

    return f"<b>{email_addr}</b>\nKhong co du lieu phu hop."


_URL_RE = re.compile(r'https?://[^\s<>"\')]+')


def _linkify_plain(text: str, max_len: int = 3500) -> tuple[str, list[tuple[str, str]]]:
    """Text thuan -> Telegram HTML voi URL bam duoc + danh sach link."""
    if not text:
        return "", []
    text = text[:max_len]
    links: list[tuple[str, str]] = []
    placeholders: dict[str, str] = {}

    from features.readmail.code_extractor import short_link_label

    def _repl(m: "re.Match") -> str:
        url = m.group(0)
        display = short_link_label(url, url)
        idx = len(links)
        links.append((display, url))
        token = f"\x00U{idx}\x00"
        placeholders[token] = (url, display)
        return token

    text = _URL_RE.sub(_repl, text)
    text = html.escape(text)
    for token, (url, display) in placeholders.items():
        safe_url = html.escape(url, quote=True)
        safe_label = html.escape(display) or safe_url
        text = text.replace(token, f'<a href="{safe_url}">{safe_label}</a>')
    text = re.sub(r"\x00U?\d*\x00?", "", text)
    return text, links


def _format_mail_detail(result: dict) -> tuple[str, list[tuple[str, str]]]:
    """Format chi tiet email -> (telegram_html, links).

    Giu link bam duoc; tra ve danh sach link de tao nut mo webview.
    """
    email_addr = html.escape(result.get("email", ""))
    status = result.get("status", "")

    if status == "error":
        error = html.escape(result.get("error", "Loi khong xac dinh"))
        return f"<b>{email_addr}</b>\n{error}", []

    data = result.get("data")
    if not data:
        return f"<b>{email_addr}</b>\nKhong co du lieu.", []

    subject = html.escape(data.get("subject", "(Khong co tieu de)"))
    from_name = html.escape(data.get("from_name", ""))
    from_addr = html.escape(data.get("from_address", ""))
    date = html.escape(data.get("date", "")[:19])
    content_type = data.get("content_type", "text")

    # Xu ly body — giu link bam duoc
    body = data.get("html_body", "")
    links: list[tuple[str, str]] = []
    if content_type == "html":
        from features.readmail.code_extractor import render_email_html
        body_text, links = render_email_html(body)
    else:
        body_text, links = _linkify_plain(body)

    if not body_text:
        body_text = "(Khong co noi dung)"

    code_info = data.get("code")
    code_line = ""
    if code_info:
        code_val = html.escape(str(code_info.get("value", "")))
        code_line = f"\n<b>Code: {code_val}</b>\n"

    lines = [
        f"<b>{subject}</b>",
        f"{from_name} &lt;{from_addr}&gt;",
        f"{date}",
        code_line,
        "─" * 30,
        body_text,
    ]

    return "\n".join(lines), links


_GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _is_valid_tenant(value: str) -> bool:
    """Kiem tra truong thu 5 co phai tenant_id hop le khong.

    Giong isValidTenantId() trong web UI goc: chi nhan
    consumers/common/organizations hoac GUID. Neu khong (VD email phu
    cua reseller) thi bo qua, dung 'consumers' — tranh loi AADSTS900144.
    """
    if not value:
        return False
    v = value.strip().lower()
    if v in ("consumers", "common", "organizations"):
        return True
    return bool(_GUID_RE.match(v))


def _parse_account_index(args: str, accounts: list) -> tuple[int | None, str | None]:
    """Parse so thu tu tai khoan tu tham so lenh. Tra ve (index, error)."""
    if not args or not args.strip():
        return None, "Vui long chi dinh so thu tu tai khoan. VD: /mail 1"

    parts = args.strip().split()
    try:
        idx = int(parts[0]) - 1
    except ValueError:
        return None, f"So thu tu khong hop le: {html.escape(parts[0])}"

    if idx < 0 or idx >= len(accounts):
        return None, f"Tai khoan #{parts[0]} khong ton tai. Ban co {len(accounts)} tai khoan."

    return idx, None


# ═══════════════════════════════════════════════════════════════════════════
# INLINE KEYBOARD — Menu nut bam
# ═══════════════════════════════════════════════════════════════════════════


def kb_accounts_list(accounts: list) -> InlineKeyboardMarkup:
    """Ban phim: danh sach tai khoan (moi tai khoan mot nut) + nut them."""
    rows = []
    for acc in accounts:
        label = f"{acc.email or '???'}"
        note = (getattr(acc, "note", "") or "").strip()
        if note:
            note_short = note if len(note) <= 18 else note[:18] + "…"
            label = f"{label} ({note_short})"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"rm:acc:{acc.id}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="Thêm mail", callback_data="rm:add")
    ])
    if accounts:
        rows.append([
            InlineKeyboardButton(
                text="Xoá tất cả tài khoản", callback_data="rm:delall",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_confirm_delete_all() -> InlineKeyboardMarkup:
    """Ban phim: xac nhan xoa TOAN BO tai khoan."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Xoá tất cả", callback_data="rm:delallok",
            ),
            InlineKeyboardButton(text="Huỷ", callback_data="rm:menu"),
        ],
    ])


def kb_account_menu(account_id: int) -> InlineKeyboardMarkup:
    """Ban phim: menu chuc nang cho mot tai khoan."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Đọc mail", callback_data=f"rm:read:{account_id}",
            ),
            InlineKeyboardButton(
                text="Lấy code", callback_data=f"rm:code:{account_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="Tất cả code", callback_data=f"rm:codes:{account_id}",
            ),
            InlineKeyboardButton(
                text="Xuất TK", callback_data=f"rm:export:{account_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="Ghi chú", callback_data=f"rm:note:{account_id}",
            ),
            InlineKeyboardButton(
                text="Xóa", callback_data=f"rm:del:{account_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="Danh sách mail", callback_data="rm:menu",
            ),
        ],
    ])


def kb_mail_page(
    account_id: int,
    page_msgs: list[dict],
    start_num: int,
    base_url: str,
    user_id: int,
    is_group: bool,
    has_more: bool = False,
    next_offset: int = 0,
) -> InlineKeyboardMarkup:
    """Ban phim danh sach mail: moi mail 1 nut mo webview + xem them + quay lai.

    - Chat rieng + base_url https: dung web_app -> mo webview NGAY trong Telegram.
    - Nhom hoac base_url http: dung nut url thuong.
    """
    from core.mailtoken import make_mail_token

    use_webapp = bool(base_url) and (not is_group) and base_url.startswith("https://")
    rows = []
    for i, m in enumerate(page_msgs):
        if not base_url:
            break  # chua cau hinh PUBLIC_BASE_URL -> khong tao nut mo webview
        num = start_num + i
        mid = m.get("id", "")
        if not mid:
            continue
        token = make_mail_token(user_id, account_id, mid)
        url = f"{base_url}/mail/view/?t={token}"
        subject = (m.get("subject") or "(khong tieu de)").strip()
        if len(subject) > 28:
            subject = subject[:28] + "…"
        label = f"#{num} {subject}"
        if use_webapp:
            rows.append([InlineKeyboardButton(
                text=label, web_app=WebAppInfo(url=url),
            )])
        else:
            rows.append([InlineKeyboardButton(text=label, url=url)])

    if has_more:
        rows.append([InlineKeyboardButton(
            text="Xem thêm", callback_data=f"rm:more:{account_id}:{next_offset}",
        )])

    rows.append([
        InlineKeyboardButton(
            text="Đọc lại", callback_data=f"rm:read:{account_id}",
        ),
        InlineKeyboardButton(
            text="Quay lại", callback_data=f"rm:acc:{account_id}",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_confirm_delete(account_id: int) -> InlineKeyboardMarkup:
    """Ban phim: xac nhan xoa tai khoan."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Xóa", callback_data=f"rm:delok:{account_id}",
            ),
            InlineKeyboardButton(
                text="Hủy", callback_data=f"rm:acc:{account_id}",
            ),
        ],
    ])


def kb_back_to_account(account_id: int) -> InlineKeyboardMarkup:
    """Ban phim: quay lai menu tai khoan."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Quay lại", callback_data=f"rm:acc:{account_id}",
        )],
    ])


def kb_mail_detail(
    account_id: int,
    links: list[tuple[str, str]],
    is_group: bool,
) -> InlineKeyboardMarkup:
    """Ban phim chi tiet mail: nut mo link (webview) + quay lai.

    - Chat rieng: dung web_app -> mo NGAY trong Telegram (khong nhay ra ngoai).
    - Trong nhom: web_app khong dung duoc -> dung nut url (mo trinh duyet in-app
      tren mobile, hoac trinh duyet ngoai tren desktop).
    """
    rows = []
    seen_url = set()
    seen_label = set()
    n = 0
    for label, url in links:
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        if url in seen_url:
            continue
        disp = (label or url).strip()
        if len(disp) > 32:
            disp = disp[:32] + "…"
        # Gop cac nut trung nhan (VD nhieu link tracking cung ten mien)
        key = disp.lower()
        if key in seen_label:
            continue
        seen_url.add(url)
        seen_label.add(key)
        if (not is_group) and url.startswith("https://"):
            rows.append([InlineKeyboardButton(
                text=disp, web_app=WebAppInfo(url=url),
            )])
        else:
            rows.append([InlineKeyboardButton(text=disp, url=url)])
        n += 1
        if n >= 8:
            break

    rows.append([InlineKeyboardButton(
        text="Quay lại", callback_data=f"rm:acc:{account_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _safe_delete(msg) -> None:
    """Xoa mot tin nhan, bo qua loi (qua han, da xoa, khong co quyen)."""
    try:
        await msg.delete()
    except Exception:
        pass


async def _send_long_result(
    cq: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
    delete_old: bool = False,
) -> None:
    """Gui ket qua dai qua callback: chia nho, keyboard o phan cuoi.

    delete_old=True: xoa tin nhan chua nut vua bam (cho gon chat).
    """
    if delete_old and cq.message:
        await _safe_delete(cq.message)
    parts = _split_message(text)
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        await cq.message.answer(
            part,
            parse_mode="HTML",
            reply_markup=keyboard if is_last else None,
        )


# ═══════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════


@router.message(Command("them", "addmail"))
async def cmd_addmail(message: types.Message, state: FSMContext, db_user) -> None:
    """Bat dau them tai khoan mail (/them hoac /addmail)."""
    await state.set_state(AddMailStates.waiting_for_credentials)
    await message.answer(
        "<b>Thêm tài khoản mail</b>\n\n"
        "Gửi thông tin theo định dạng:\n"
        "<code>email|password|refresh_token|client_id</code>\n"
        "hoặc kèm tenant_id:\n"
        "<code>email|password|refresh_token|client_id|tenant_id</code>\n\n"
        "Bot chỉ dùng <b>refresh_token</b> và <b>client_id</b> để đọc mail. "
        "Trường <b>password</b> không được dùng (chỉ có sẵn trong combo).\n\n"
        "Có thể gửi nhiều dòng để thêm nhiều tài khoản cùng lúc, "
        "hoặc gửi thẳng một file <b>.txt</b> (bot tự đọc và nhập).\n\n"
        "Gửi /cancel để hủy.",
        parse_mode="HTML",
    )


async def _import_credentials_text(
    message: types.Message, state: FSMContext, db_user, text: str,
) -> None:
    """Parse + import tai khoan tu text. Dung chung cho tin nhan va file .txt."""
    from core.db import add_mail_account, get_user_accounts

    # Chuan hoa: chu nghieng/dam kieu unicode -> ASCII, bo ky tu vo hinh.
    text = _normalize_input(text)

    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    if not lines:
        await state.clear()
        await message.answer(
            "Không có dữ liệu. Gửi lại theo định dạng:\n"
            "<code>email|password|refresh_token|client_id[|tenant_id]</code>",
            parse_mode="HTML",
        )
        return

    results = []
    added_any = False
    for line in lines:
        parts = line.split("|")
        # Dinh dang: email|password|refresh_token|client_id[|tenant_id]
        if len(parts) < 4:
            results.append(f"Sai định dạng: {html.escape(line[:50])}")
            continue

        email_addr = parts[0].strip()
        # parts[1] = password — KHONG dung, KHONG luu (chi co trong combo)
        refresh_token = parts[2].strip()
        client_id = parts[3].strip()
        raw_tenant = parts[4].strip() if len(parts) > 4 else ""
        tenant_id = raw_tenant if _is_valid_tenant(raw_tenant) else "consumers"

        if not email_addr or not refresh_token or not client_id:
            results.append(f"Thiếu thông tin: {html.escape(email_addr or line[:30])}")
            continue

        try:
            await add_mail_account(
                user_id=db_user.id,
                email=email_addr,
                refresh_token=refresh_token,
                client_id=client_id,
                tenant_id=tenant_id,
                raw_input=line,  # luu nguyen van de xuat lai y het
            )
            results.append(f"Đã thêm: {html.escape(email_addr)}")
            added_any = True
        except Exception as e:
            logger.error("Loi them tai khoan %s: %s", email_addr, e)
            results.append(f"Lỗi khi thêm {html.escape(email_addr)}: {html.escape(str(e)[:100])}")

    await state.clear()

    # Bao mat: tu xoa tin nhan chua thong tin tai khoan user vua gui.
    # CHI xoa khi co dinh dang tk (chua dau '|') -> tranh xoa nham tin khac.
    # (Chat rieng: bot xoa duoc; trong nhom: can bot la admin co quyen xoa tin.)
    if "|" in text:
        await _safe_delete(message)

    # Hien ket qua + menu nut bam cac tai khoan
    if added_any:
        accounts = await get_user_accounts(db_user.id)
        for i, part in enumerate(_split_message(
            "\n".join(results) + "\n\nChọn tài khoản để dùng:",
        )):
            await message.answer(
                part,
                parse_mode="HTML",
                reply_markup=kb_accounts_list(accounts)
                if i == 0 else None,
            )
    else:
        for part in _split_message("\n".join(results)):
            await message.answer(part, parse_mode="HTML")


@router.message(AddMailStates.waiting_for_credentials, F.text)
async def process_addmail_credentials(
    message: types.Message, state: FSMContext, db_user,
) -> None:
    """Xu ly thong tin tai khoan mail gui bang text. Sau do hien menu nut bam."""
    text = message.text or ""

    if text.strip().lower() == "/cancel":
        await state.clear()
        await _safe_delete(message)  # xoa luon tin /cancel cua user
        await message.answer("Đã hủy thêm tài khoản.")
        return

    await _import_credentials_text(message, state, db_user, text)


@router.message(AddMailStates.waiting_for_credentials, F.document)
async def process_addmail_document(
    message: types.Message, state: FSMContext, db_user,
) -> None:
    """Nhan file .txt chua combo -> tu doc noi dung va import."""
    doc = message.document
    name = (doc.file_name or "").lower()
    mime = (doc.mime_type or "").lower()
    is_txt = name.endswith(".txt") or mime.startswith("text/")
    if not is_txt:
        await message.answer(
            "Chỉ nhận file <b>.txt</b>. Gửi lại file văn bản, "
            "hoặc dán trực tiếp thông tin.\n\nGửi /cancel để hủy.",
            parse_mode="HTML",
        )
        return

    if doc.file_size and doc.file_size > _MAX_TXT_BYTES:
        await message.answer(
            "File quá lớn (giới hạn 2MB). Tách nhỏ rồi gửi lại.",
        )
        return

    try:
        buf = io.BytesIO()
        await message.bot.download(doc, destination=buf)
        raw = buf.getvalue()
    except Exception as e:
        logger.error("Loi tai file .txt: %s", e)
        await message.answer(
            "Không tải được file. Thử lại, hoặc dán trực tiếp thông tin.",
        )
        return

    # Giai ma text: thu vai bang ma pho bien roi moi bo qua ky tu loi.
    text = None
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="ignore")

    # Bao mat: xoa file combo user vua gui.
    await _safe_delete(message)

    await _import_credentials_text(message, state, db_user, text)


@router.message(Command("menu"))
async def cmd_menu(message: types.Message, db_user) -> None:
    """Hien menu nut bam danh sach tai khoan mail."""
    from core.db import get_user_accounts

    try:
        accounts = await get_user_accounts(db_user.id)
    except Exception as e:
        logger.error("Loi lay danh sach tai khoan: %s", e)
        await message.answer("Lỗi khi truy vấn cơ sở dữ liệu.")
        return

    if not accounts:
        await message.answer(
            "Bạn chưa có tài khoản mail nào.\n"
            "Dùng /them để thêm tài khoản.",
            parse_mode="HTML",
        )
        return

    await message.answer(
        "<b>Chọn tài khoản mail:</b>",
        parse_mode="HTML",
        reply_markup=kb_accounts_list(accounts),
    )


@router.message(Command("listmail"))
async def cmd_listmail(message: types.Message, db_user) -> None:
    """Liet ke cac tai khoan mail da luu."""
    from core.db import get_user_accounts

    try:
        accounts = await get_user_accounts(db_user.id)
    except Exception as e:
        logger.error("Loi lay danh sach tai khoan: %s", e)
        await message.answer("Lỗi khi truy vấn cơ sở dữ liệu.")
        return

    if not accounts:
        await message.answer(
            "Bạn chưa có tài khoản mail nào.\n"
            "Dùng /them để thêm tài khoản.",
            parse_mode="HTML",
        )
        return

    lines = ["<b>Danh sách tài khoản mail:</b>\n"]
    for i, acc in enumerate(accounts, 1):
        email_addr = html.escape(acc.email or "???")
        tenant = html.escape(acc.tenant_id or "consumers")
        lines.append(f"  <b>{i}.</b> {email_addr} (tenant: {tenant})")

    lines.append(f"\nTong: {len(accounts)} tai khoan")
    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb_accounts_list(accounts),
    )


@router.message(Command("delmail"))
async def cmd_delmail(message: types.Message, db_user) -> None:
    """Xoa tai khoan mail theo so thu tu."""
    from core.db import get_user_accounts, remove_mail_account

    args = (message.text or "").replace("/delmail", "", 1).strip()
    if not args:
        await message.answer(
            "Vui lòng chỉ định số thứ tự.\n"
            "VD: <code>/delmail 1</code>",
            parse_mode="HTML",
        )
        return

    try:
        accounts = await get_user_accounts(db_user.id)
    except Exception as e:
        logger.error("Loi lay danh sach tai khoan: %s", e)
        await message.answer("Lỗi khi truy vấn cơ sở dữ liệu.")
        return

    idx, error = _parse_account_index(args, accounts)
    if error:
        await message.answer(f"{error}", parse_mode="HTML")
        return

    account = accounts[idx]
    email_addr = html.escape(account.email or "???")

    try:
        await remove_mail_account(account.id)
        await message.answer(f"Đã xóa tài khoản: {email_addr}", parse_mode="HTML")
    except Exception as e:
        logger.error("Loi xoa tai khoan: %s", e)
        await message.answer(
            f"Lỗi khi xóa {email_addr}: {html.escape(str(e)[:100])}",
            parse_mode="HTML",
        )


@router.message(Command("mail"))
async def cmd_mail(message: types.Message, db_user) -> None:
    """Doc email moi nhat cho mot tai khoan."""
    from core.db import get_user_accounts

    args = (message.text or "").replace("/mail", "", 1).strip()

    try:
        accounts = await get_user_accounts(db_user.id)
    except Exception as e:
        logger.error("Loi lay danh sach tai khoan: %s", e)
        await message.answer("Lỗi khi truy vấn cơ sở dữ liệu.")
        return

    if not accounts:
        await message.answer("Bạn chưa có tài khoản mail nào. Dùng /them để thêm.")
        return

    idx, error = _parse_account_index(args, accounts)
    if error:
        await message.answer(f"{error}", parse_mode="HTML")
        return

    # Parse limit tu tham so thu 2
    parts = args.strip().split()
    limit = 5
    if len(parts) > 1:
        try:
            limit = int(parts[1])
            limit = max(1, min(limit, 50))
        except ValueError:
            pass

    loading_msg = await message.answer("Đang đọc mail...")

    account = accounts[idx]
    account_dict = _account_to_dict(account)
    result = await async_read_mail(account_dict, limit)

    if result["status"] == "error":
        error_text = html.escape(result.get("error", "Loi khong xac dinh"))
        await loading_msg.edit_text(
            f"<b>{html.escape(account.email or '')}</b>\n{error_text}",
            parse_mode="HTML",
        )
        return

    formatted = _format_mail_list(result["data"], account.email or "")
    parts = _split_message(formatted)

    await loading_msg.edit_text(parts[0], parse_mode="HTML")
    for part in parts[1:]:
        await message.answer(part, parse_mode="HTML")


@router.message(Command("readall"))
async def cmd_readall(message: types.Message, db_user) -> None:
    """Doc email moi nhat tu tat ca tai khoan."""
    from core.db import get_user_accounts

    try:
        accounts = await get_user_accounts(db_user.id)
    except Exception as e:
        logger.error("Loi lay danh sach tai khoan: %s", e)
        await message.answer("Lỗi khi truy vấn cơ sở dữ liệu.")
        return

    if not accounts:
        await message.answer("Bạn chưa có tài khoản mail nào. Dùng /them để thêm.")
        return

    loading_msg = await message.answer(
        f"Đang đọc mail từ {len(accounts)} tài khoản..."
    )

    account_dicts = [_account_to_dict(acc) for acc in accounts]
    results = await async_read_all_accounts(account_dicts, limit=1)

    output_parts = []
    for result in results:
        email_addr = html.escape(result.get("email", "???"))
        if result["status"] == "error":
            error_text = html.escape(result.get("error", "")[:150])
            output_parts.append(f"<b>{email_addr}</b>\n   {error_text}\n")
        else:
            formatted = _format_mail_list(result["data"], result.get("email", ""))
            output_parts.append(formatted)

    full_output = "\n".join(output_parts)
    parts = _split_message(full_output)

    await loading_msg.edit_text(parts[0], parse_mode="HTML")
    for part in parts[1:]:
        await message.answer(part, parse_mode="HTML")


@router.message(Command("code"))
async def cmd_code(message: types.Message, db_user) -> None:
    """Tim ma xac nhan tot nhat tu tai khoan."""
    from core.db import get_user_accounts

    args = (message.text or "").replace("/code", "", 1).strip()

    try:
        accounts = await get_user_accounts(db_user.id)
    except Exception as e:
        logger.error("Loi lay danh sach tai khoan: %s", e)
        await message.answer("Lỗi khi truy vấn cơ sở dữ liệu.")
        return

    if not accounts:
        await message.answer("Bạn chưa có tài khoản mail nào. Dùng /them để thêm.")
        return

    idx, error = _parse_account_index(args, accounts)
    if error:
        await message.answer(f"{error}", parse_mode="HTML")
        return

    parts = args.strip().split()
    limit = 5
    if len(parts) > 1:
        try:
            limit = int(parts[1])
            limit = max(1, min(limit, 50))
        except ValueError:
            pass

    loading_msg = await message.answer("Đang tìm mã xác nhận...")

    account = accounts[idx]
    result = await async_get_code(_account_to_dict(account), limit)
    formatted = _format_code_result(result)

    parts_msg = _split_message(formatted)
    await loading_msg.edit_text(parts_msg[0], parse_mode="HTML")
    for part in parts_msg[1:]:
        await message.answer(part, parse_mode="HTML")


@router.message(Command("codes"))
async def cmd_codes(message: types.Message, db_user) -> None:
    """Tim tat ca ma xac nhan tu tai khoan."""
    from core.db import get_user_accounts

    args = (message.text or "").replace("/codes", "", 1).strip()

    try:
        accounts = await get_user_accounts(db_user.id)
    except Exception as e:
        logger.error("Loi lay danh sach tai khoan: %s", e)
        await message.answer("Lỗi khi truy vấn cơ sở dữ liệu.")
        return

    if not accounts:
        await message.answer("Bạn chưa có tài khoản mail nào. Dùng /them để thêm.")
        return

    idx, error = _parse_account_index(args, accounts)
    if error:
        await message.answer(f"{error}", parse_mode="HTML")
        return

    parts = args.strip().split()
    limit = 5
    if len(parts) > 1:
        try:
            limit = int(parts[1])
            limit = max(1, min(limit, 50))
        except ValueError:
            pass

    loading_msg = await message.answer("Đang tìm tất cả mã xác nhận...")

    account = accounts[idx]
    result = await async_get_all_codes(_account_to_dict(account), limit)
    formatted = _format_code_result(result)

    parts_msg = _split_message(formatted)
    await loading_msg.edit_text(parts_msg[0], parse_mode="HTML")
    for part in parts_msg[1:]:
        await message.answer(part, parse_mode="HTML")


@router.message(Command("maildetail"))
async def cmd_maildetail(
    message: types.Message, db_user, is_group: bool = False,
) -> None:
    """Doc chi tiet mot email."""
    from core.db import get_user_accounts

    args = (message.text or "").replace("/maildetail", "", 1).strip()
    parts = args.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "Vui lòng chỉ định số thứ tự và message ID.\n"
            "VD: <code>/maildetail 1 AAMkAGI2...</code>",
            parse_mode="HTML",
        )
        return

    try:
        accounts = await get_user_accounts(db_user.id)
    except Exception as e:
        logger.error("Loi lay danh sach tai khoan: %s", e)
        await message.answer("Lỗi khi truy vấn cơ sở dữ liệu.")
        return

    if not accounts:
        await message.answer("Bạn chưa có tài khoản mail nào. Dùng /them để thêm.")
        return

    idx, error = _parse_account_index(parts[0], accounts)
    if error:
        await message.answer(f"{error}", parse_mode="HTML")
        return

    message_id = parts[1].strip()
    if not message_id:
        await message.answer("Vui lòng cung cấp message ID.")
        return

    loading_msg = await message.answer("Đang đọc chi tiết email...")

    account = accounts[idx]
    result = await async_mail_detail(_account_to_dict(account), message_id)
    formatted, links = _format_mail_detail(result)
    keyboard = kb_mail_detail(account.id, links, is_group) if links else None

    parts_msg = _split_message(formatted)
    last = len(parts_msg) - 1
    for i, part in enumerate(parts_msg):
        kb = keyboard if i == last else None
        if i == 0:
            await loading_msg.edit_text(part, parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer(part, parse_mode="HTML", reply_markup=kb)


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK HANDLERS — Xu ly nut bam
# ═══════════════════════════════════════════════════════════════════════════


async def _get_account(db_user, account_id: int):
    """Lay tai khoan theo id, kiem tra thuoc ve user."""
    from core.db import get_user_accounts

    accounts = await get_user_accounts(db_user.id)
    for acc in accounts:
        if acc.id == account_id:
            return acc, accounts
    return None, accounts


@router.callback_query(F.data == "rm:menu")
async def cb_menu(cq: CallbackQuery, db_user) -> None:
    """Nut: quay ve danh sach tai khoan."""
    from core.db import get_user_accounts

    accounts = await get_user_accounts(db_user.id)
    await cq.answer()

    if not accounts:
        await cq.message.edit_text(
            "Bạn chưa có tài khoản mail nào. Dùng /them để thêm.",
        )
        return

    await cq.message.edit_text(
        "<b>Chọn tài khoản mail:</b>",
        parse_mode="HTML",
        reply_markup=kb_accounts_list(accounts),
    )


@router.callback_query(F.data == "rm:add")
async def cb_add(cq: CallbackQuery, state: FSMContext, db_user) -> None:
    """Nut: them tai khoan moi."""
    await cq.answer()
    await _safe_delete(cq.message)
    await state.set_state(AddMailStates.waiting_for_credentials)
    await cq.message.answer(
        "<b>Thêm tài khoản mail</b>\n\n"
        "Gửi thông tin theo định dạng:\n"
        "<code>email|password|refresh_token|client_id[|tenant_id]</code>\n\n"
        "Bot chỉ dùng refresh_token và client_id (password không dùng).\n\n"
        "Gửi /cancel để hủy.",
        parse_mode="HTML",
    )


def _account_menu_header(account, prefix: str = "") -> str:
    """Tao phan text tieu de cho menu mot tai khoan (kem ghi chu neu co)."""
    header = prefix
    header += f"<b>{html.escape(account.email or '???')}</b>\n"
    note = (getattr(account, "note", "") or "").strip()
    if note:
        header += f"Ghi chú: {html.escape(note)}\n"
    header += "Chọn chức năng:"
    return header


@router.callback_query(F.data.startswith("rm:acc:"))
async def cb_account_menu(cq: CallbackQuery, db_user) -> None:
    """Nut: hien menu chuc nang cho mot tai khoan."""
    account_id = int(cq.data.split(":")[2])
    account, _ = await _get_account(db_user, account_id)
    await cq.answer()

    if account is None:
        await cq.message.edit_text("Tài khoản không tồn tại.")
        return

    await cq.message.edit_text(
        _account_menu_header(account),
        parse_mode="HTML",
        reply_markup=kb_account_menu(account_id),
    )


@router.callback_query(F.data.startswith("rm:export:"))
async def cb_export(cq: CallbackQuery, db_user) -> None:
    """Nut: xuat tai khoan y het luc nhap + ghi chu."""
    account_id = int(cq.data.split(":")[2])
    account, _ = await _get_account(db_user, account_id)
    await cq.answer()
    if account is None:
        await cq.message.edit_text("Tài khoản không tồn tại.")
        return

    raw = (getattr(account, "raw_input", "") or "").strip()
    extra = ""
    if raw:
        line = raw
    else:
        # Tai khoan cu (them truoc khi co tinh nang) -> dung lai tu cac truong,
        # khong co password.
        parts = [
            account.email or "",
            account.refresh_token or "",
            account.client_id or "",
        ]
        if account.tenant_id and account.tenant_id != "consumers":
            parts.append(account.tenant_id)
        line = "|".join(parts)
        extra = "\n\n(Tài khoản thêm trước khi có tính năng này nên không lưu password)"

    note = (getattr(account, "note", "") or "").strip()
    text = (
        "<b>Xuất tài khoản</b>\n"
        f"{html.escape(account.email or '')}\n\n"
        f"<code>{html.escape(line)}</code>"
    )
    if note:
        text += f"\n\nGhi chú:\n{html.escape(note)}"
    text += extra

    await _safe_delete(cq.message)
    await cq.message.answer(
        text, parse_mode="HTML", reply_markup=kb_back_to_account(account_id),
    )


@router.callback_query(F.data.startswith("rm:note:"))
async def cb_note(cq: CallbackQuery, state: FSMContext, db_user) -> None:
    """Nut: nhap/sua ghi chu cho tai khoan."""
    account_id = int(cq.data.split(":")[2])
    account, _ = await _get_account(db_user, account_id)
    await cq.answer()
    if account is None:
        await cq.message.edit_text("Tài khoản không tồn tại.")
        return

    # Xoa menu tai khoan cu cho gon; se hien lai menu sau khi luu ghi chu
    await _safe_delete(cq.message)

    cur = (getattr(account, "note", "") or "").strip()
    msg = f"Gửi ghi chú cho <b>{html.escape(account.email or '')}</b>.\n"
    if cur:
        msg += f"Ghi chú hiện tại: {html.escape(cur)}\n"
    msg += "Gửi nội dung mới, /xoa để xoá ghi chú, hoặc /cancel để hủy."
    sent = await cq.message.answer(msg, parse_mode="HTML")

    await state.set_state(NoteStates.waiting_for_note)
    await state.update_data(
        note_account_id=account_id,
        prompt_chat_id=sent.chat.id,
        prompt_msg_id=sent.message_id,
    )


@router.message(NoteStates.waiting_for_note)
async def process_note(
    message: types.Message, state: FSMContext, db_user,
) -> None:
    """Luu ghi chu, sau do xoa tin nhan user + tin bot hoi, quay ve menu tk."""
    from core.db import set_account_note

    text = (message.text or "").strip()
    data = await state.get_data()
    account_id = data.get("note_account_id")
    prompt_chat = data.get("prompt_chat_id")
    prompt_id = data.get("prompt_msg_id")
    await state.clear()

    # Xoa tin nhan user vua gui (noi dung ghi chu) va tin bot hoi truoc do
    await _safe_delete(message)
    if prompt_chat and prompt_id:
        try:
            await message.bot.delete_message(prompt_chat, prompt_id)
        except Exception:
            pass

    if not account_id:
        await message.answer("Đã hết phiên. Mở lại bằng /menu.")
        return

    account, _ = await _get_account(db_user, account_id)
    if account is None:
        await message.answer("Tài khoản không tồn tại.")
        return

    # Khong co noi dung hoac /cancel -> quay ve menu, khong doi ghi chu
    if not text or text.lower() == "/cancel":
        await message.answer(
            _account_menu_header(account),
            parse_mode="HTML",
            reply_markup=kb_account_menu(account_id),
        )
        return

    new_note = "" if text.lower() == "/xoa" else text
    try:
        await set_account_note(account_id, new_note)
    except Exception as e:
        logger.error("Loi luu ghi chu: %s", e)
        await message.answer(
            f"Lỗi khi lưu ghi chú: {html.escape(str(e)[:100])}",
            parse_mode="HTML",
        )
        return

    account.note = new_note  # cap nhat trong bo nho de header hien dung
    prefix = "Đã lưu ghi chú.\n" if new_note else "Đã xoá ghi chú.\n"
    await message.answer(
        _account_menu_header(account, prefix=prefix),
        parse_mode="HTML",
        reply_markup=kb_account_menu(account_id),
    )


# So mail moi trang (chi hien "Xem them" khi con nhieu hon PAGE_SIZE mail)
PAGE_SIZE = 10


async def _render_list_page(
    cq: CallbackQuery, db_user, account,
    full: list[dict], offset: int, is_group: bool,
) -> None:
    """Hien danh sach mail gon (gio, tieu de, nguoi gui, trich doan)
    + nut mo webview cho tung mail + nut xem them.
    Tu xoa tin nhan cu (tin chua nut vua bam) cho gon chat."""
    account_id = account.id
    page = full[offset:offset + PAGE_SIZE]
    if not page:
        await _safe_delete(cq.message)
        await cq.message.answer(
            "Hết mail.", reply_markup=kb_back_to_account(account_id),
        )
        return

    from core.db import get_setting
    base_url = (await get_setting("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

    has_more = len(full) > offset + PAGE_SIZE
    formatted = _format_mail_list(page, account.email or "", start=offset + 1)
    if not base_url:
        formatted += (
            "\nChưa cấu hình PUBLIC_BASE_URL (Admin → Bot Settings) "
            "nên chưa mở được webview xem mail."
        )
    kb = kb_mail_page(
        account_id, page, offset + 1, base_url, db_user.id,
        is_group, has_more, offset + PAGE_SIZE,
    )
    await _send_long_result(cq, formatted, kb, delete_old=True)


@router.callback_query(F.data.startswith("rm:read:"))
async def cb_read(cq: CallbackQuery, db_user, is_group: bool = False) -> None:
    """Nut: doc mail -> danh sach gon + nut mo webview tung mail."""
    account_id = int(cq.data.split(":")[2])
    account, _ = await _get_account(db_user, account_id)
    if account is None:
        await cq.answer("Tài khoản không tồn tại.", show_alert=True)
        return

    await cq.answer("Đang đọc mail...")
    result = await async_read_mail(
        _account_to_dict(account), limit=PAGE_SIZE + 1,
    )
    if result["status"] == "error":
        error_text = html.escape(result.get("error", "Loi khong xac dinh"))
        await _safe_delete(cq.message)
        await cq.message.answer(
            f"<b>{html.escape(account.email or '')}</b>\n{error_text}",
            parse_mode="HTML",
            reply_markup=kb_back_to_account(account_id),
        )
        return

    messages = result["data"]
    if not messages:
        await _safe_delete(cq.message)
        await cq.message.answer(
            f"<b>{html.escape(account.email or '')}</b>\nKhông có mail nào.",
            parse_mode="HTML",
            reply_markup=kb_back_to_account(account_id),
        )
        return

    await _render_list_page(cq, db_user, account, messages, 0, is_group)


@router.callback_query(F.data.startswith("rm:more:"))
async def cb_more(cq: CallbackQuery, db_user, is_group: bool = False) -> None:
    """Nut: xem them mail (trang tiep theo)."""
    parts = cq.data.split(":")
    account_id = int(parts[2])
    offset = int(parts[3])
    account, _ = await _get_account(db_user, account_id)
    if account is None:
        await cq.answer("Tài khoản không tồn tại.", show_alert=True)
        return

    await cq.answer("Đang tải thêm...")
    need = offset + PAGE_SIZE + 1
    result = await async_read_mail(_account_to_dict(account), limit=need)
    if result["status"] == "error":
        error_text = html.escape(result.get("error", "Loi khong xac dinh"))
        await _safe_delete(cq.message)
        await cq.message.answer(
            f"<b>{html.escape(account.email or '')}</b>\n{error_text}",
            parse_mode="HTML",
            reply_markup=kb_back_to_account(account_id),
        )
        return

    await _render_list_page(cq, db_user, account, result["data"], offset, is_group)


@router.callback_query(F.data.startswith("rm:code:"))
async def cb_code(cq: CallbackQuery, db_user) -> None:
    """Nut: lay ma xac nhan moi nhat."""
    account_id = int(cq.data.split(":")[2])
    account, _ = await _get_account(db_user, account_id)

    if account is None:
        await cq.answer("Tài khoản không tồn tại.", show_alert=True)
        return

    await cq.answer("Đang tìm mã...")

    result = await async_get_code(_account_to_dict(account), limit=5)
    formatted = _format_code_result(result)
    await _send_long_result(
        cq, formatted, kb_back_to_account(account_id), delete_old=True,
    )


@router.callback_query(F.data.startswith("rm:codes:"))
async def cb_codes(cq: CallbackQuery, db_user) -> None:
    """Nut: lay tat ca ma xac nhan."""
    account_id = int(cq.data.split(":")[2])
    account, _ = await _get_account(db_user, account_id)

    if account is None:
        await cq.answer("Tài khoản không tồn tại.", show_alert=True)
        return

    await cq.answer("Đang tìm tất cả mã...")

    result = await async_get_all_codes(_account_to_dict(account), limit=5)
    formatted = _format_code_result(result)
    await _send_long_result(
        cq, formatted, kb_back_to_account(account_id), delete_old=True,
    )


@router.callback_query(F.data.startswith("rm:detail:"))
async def cb_detail(cq: CallbackQuery, db_user, is_group: bool = False) -> None:
    """Nut: xem chi tiet mot mail (theo so thu tu trong cache)."""
    parts = cq.data.split(":")
    account_id = int(parts[2])
    msg_idx = int(parts[3])

    account, _ = await _get_account(db_user, account_id)
    if account is None:
        await cq.answer("Tài khoản không tồn tại.", show_alert=True)
        return

    cached = _mail_cache.get((db_user.id, account_id))
    if not cached or msg_idx >= len(cached):
        await cq.answer(
            "Danh sách mail đã hết hạn. Bấm 'Đọc lại'.", show_alert=True,
        )
        return

    message_id = cached[msg_idx].get("id", "")
    if not message_id:
        await cq.answer("Không có ID mail.", show_alert=True)
        return

    await cq.answer("Đang đọc chi tiết...")

    result = await async_mail_detail(_account_to_dict(account), message_id)
    formatted, links = _format_mail_detail(result)
    keyboard = kb_mail_detail(account_id, links, is_group)
    await _send_long_result(cq, formatted, keyboard)


@router.callback_query(F.data.startswith("rm:del:"))
async def cb_del_confirm(cq: CallbackQuery, db_user) -> None:
    """Nut: hoi xac nhan xoa tai khoan."""
    account_id = int(cq.data.split(":")[2])
    account, _ = await _get_account(db_user, account_id)
    await cq.answer()

    if account is None:
        await cq.message.edit_text("Tài khoản không tồn tại.")
        return

    await cq.message.edit_text(
        f"Xóa tài khoản <b>{html.escape(account.email or '???')}</b>?",
        parse_mode="HTML",
        reply_markup=kb_confirm_delete(account_id),
    )


@router.callback_query(F.data.startswith("rm:delok:"))
async def cb_del_ok(cq: CallbackQuery, db_user) -> None:
    """Nut: xac nhan xoa that."""
    from core.db import get_user_accounts, remove_mail_account

    account_id = int(cq.data.split(":")[2])
    account, _ = await _get_account(db_user, account_id)

    if account is None:
        await cq.answer("Tài khoản không tồn tại.", show_alert=True)
        return

    email_addr = html.escape(account.email or "???")
    try:
        await remove_mail_account(account_id)
        _mail_cache.pop((db_user.id, account_id), None)
        await cq.answer("Đã xóa.")
    except Exception as e:
        logger.error("Loi xoa tai khoan: %s", e)
        await cq.answer(f"Lỗi: {str(e)[:100]}", show_alert=True)
        return

    # Hien lai danh sach con lai
    accounts = await get_user_accounts(db_user.id)
    if accounts:
        await cq.message.edit_text(
            f"Đã xóa {email_addr}.\n\n<b>Chọn tài khoản mail:</b>",
            parse_mode="HTML",
            reply_markup=kb_accounts_list(accounts),
        )
    else:
        await cq.message.edit_text(
            f"Đã xóa {email_addr}.\n\n"
            "Bạn chưa có tài khoản nào. Dùng /them để thêm.",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "rm:delall")
async def cb_delall_confirm(cq: CallbackQuery, db_user) -> None:
    """Nut: hoi xac nhan xoa TOAN BO tai khoan."""
    from core.db import get_user_accounts

    accounts = await get_user_accounts(db_user.id)
    await cq.answer()
    if not accounts:
        await cq.message.edit_text("Bạn chưa có tài khoản nào.")
        return
    await cq.message.edit_text(
        f"Xoá <b>toàn bộ {len(accounts)}</b> tài khoản mail? "
        "Hành động này không thể hoàn tác.",
        parse_mode="HTML",
        reply_markup=kb_confirm_delete_all(),
    )


@router.callback_query(F.data == "rm:delallok")
async def cb_delall_ok(cq: CallbackQuery, db_user) -> None:
    """Nut: xac nhan xoa TOAN BO tai khoan."""
    from core.db import remove_all_mail_accounts

    try:
        count = await remove_all_mail_accounts(db_user.id)
        # Xoa cache cua user
        for key in [k for k in _mail_cache if k[0] == db_user.id]:
            _mail_cache.pop(key, None)
        await cq.answer("Đã xoá.")
    except Exception as e:
        logger.error("Loi xoa toan bo tai khoan: %s", e)
        await cq.answer(f"Lỗi: {str(e)[:100]}", show_alert=True)
        return

    await cq.message.edit_text(
        f"Đã xoá {count} tài khoản.\n\n"
        "Bạn chưa có tài khoản nào. Dùng /them để thêm.",
        parse_mode="HTML",
    )


# ── Dang ky voi FeatureRegistry ──────────────────────────────────────────
from features.registry import FeatureRegistry

FeatureRegistry.register(
    name=FEATURE_NAME,
    description=FEATURE_DESC,
    commands=FEATURE_COMMANDS,
    router=router,
)
