"""Trich xuat ma OTP / ma xac nhan tu noi dung email."""
from __future__ import annotations

import re

# ── Pattern chinh de nhan dien ma xac nhan ──────────────────────────────
# Nhan dien: G-123456, FB-391024, 883-574, 883 574, 8F2A1K, XKJHD, 123456
CODE_PATTERN = re.compile(
    r"""
    (?:^|(?<=[\s:=\-\(\"\'""]))        # Truoc ma: dau cach, dau hai cham, dau bang, ...
    (?:
        [A-Z]{1,3}-\d{4,8}             # Ma co tien to: G-847291, FB-391024
        |\d{3,4}[\s\-]\d{3,4}          # Ma co dau gach/khoang trang: 883-574, 883 574
        |[A-Z0-9]{6,8}                 # Ma hon hop chu-so viet hoa: 8F2A1K
        |[A-Z]{4,8}                    # Chuoi chu viet hoa: XKJHD
        |\d{4,8}                       # Ma so thuan tuy: 123456
    )
    (?=$|[\s.,;:!?)\]"'])        # Sau ma: dau cach, dau cham, dau ket thuc
    """,
    re.VERBOSE | re.MULTILINE,
)

# ── Tu thuong gap bi nham la ma ─────────────────────────────────────────
COMMON_WORD_EXCLUSIONS: set[str] = {
    "below", "above", "email", "login", "verify", "click", "here",
    "link", "this", "that", "from", "your", "with", "have", "will",
    "been", "more", "about", "help", "view", "open", "like", "just",
    "back", "next", "step", "done", "sent", "note", "dear", "team",
    "best", "thank", "thanks", "free", "home", "page", "site",
    "account", "password", "update", "change", "reset", "enter",
    "submit", "confirm", "please", "hello", "welcome", "new",
    "sign", "inbox", "spam", "junk", "mail", "read", "unread",
    "reply", "forward", "delete", "draft", "http", "https", "www",
    "html", "text", "body", "head", "font", "size", "color",
    "width", "height", "style", "class", "href", "none", "auto",
    "true", "false", "null", "undefined",
}

# ── Pattern loai bo email khong phai xac nhan ────────────────────────────
NEGATIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(?:order|invoice|receipt|tracking)\s*(?:#|number|no\.?)\s*", re.IGNORECASE),
    re.compile(r"(?i)(?:unsubscribe|newsletter|subscription|marketing)", re.IGNORECASE),
    re.compile(r"(?i)(?:invoice|bill|payment\s+confirmation|purchase)", re.IGNORECASE),
    re.compile(r"(?i)(?:shipping|delivery|shipment|tracking)", re.IGNORECASE),
]

# ── Pattern ngu canh do tin cay cao ──────────────────────────────────────
# Ho tro ca tieng Viet (khong dau) va tieng Anh
CONTEXTUAL_PATTERNS: list[re.Pattern] = [
    # Tieng Viet
    re.compile(
        r"(?:ma\s+xac\s+nhan|ma\s+OTP|nhap\s+ma|ma\s+bao\s+mat|ma\s+xac\s+thuc|"
        r"ma\s+dang\s+nhap|ma\s+cua\s+ban|su\s+dung\s+ma)"
        r"[\s:]*\s*([A-Z0-9][\w\-\s]{2,10}[A-Z0-9]|\d{4,8})",
        re.IGNORECASE,
    ),
    # Tieng Anh - "your code is XXX", "verification code: XXX"
    re.compile(
        r"(?:verification\s+code|security\s+code|confirmation\s+code|"
        r"your\s+code\s+is|your\s+code:|one[- ]?time\s+(?:pass)?code|"
        r"OTP|passcode|pin\s+code|access\s+code|sign[- ]?in\s+code|"
        r"login\s+code|two[- ]?factor\s+code|2FA\s+code|"
        r"temporary\s+(?:pass)?code|use\s+code|enter\s+code|"
        r"enter\s+the\s+following\s+code)"
        r"[\s:]*\s*([A-Z0-9][\w\-\s]{2,10}[A-Z0-9]|\d{4,8})",
        re.IGNORECASE,
    ),
    # Dang: "XXX is your code"
    re.compile(
        r"([A-Z0-9][\w\-]{2,10}[A-Z0-9]|\d{4,8})"
        r"\s+(?:is\s+your|la\s+ma)\s+"
        r"(?:verification|security|confirmation|one[- ]?time|"
        r"OTP|login|sign[- ]?in|xac\s+nhan|xac\s+thuc|dang\s+nhap)"
        r"\s*(?:code|ma)?",
        re.IGNORECASE,
    ),
]

# ── Tu khoa xac dinh email xac nhan ─────────────────────────────────────
VERIFICATION_KEYWORDS: list[str] = [
    "verification", "verify", "code", "otp", "one-time", "one time",
    "passcode", "pass code", "security code", "confirmation code",
    "sign-in", "sign in", "login code", "two-factor", "2fa",
    "xac nhan", "xac thuc", "ma otp", "ma bao mat", "dang nhap",
]


def clean_code_value(code: str) -> str:
    """Loai bo tien to thuong hieu: G-847291 -> 847291, FB-391024 -> 391024."""
    # Tien to 1-3 ky tu viet hoa + dau gach
    cleaned = re.sub(r"^[A-Z]{1,3}-", "", code.strip())
    return cleaned.strip()


def _clean_html_to_text(html: str) -> str:
    """Chuyen HTML sang text thuan."""
    if not html:
        return ""
    # Thay <br>, <p>, <div> bang xuong dong
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<(?:p|div)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Xoa tat ca the HTML
    text = re.sub(r"<[^>]+>", "", text)
    # Giai ma entity HTML co ban
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")
    # Xoa khoang trang thua
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def short_link_label(label: str, url: str, max_len: int = 40) -> str:
    """Rut gon nhan link: neu nhan la URL / rong / qua dai -> dung ten mien.

    VD: 'https://url8792.mail.anthropic.com/ls/click?upn=...' -> 'url8792.mail.anthropic.com'
        'Sign in to Claude.ai' -> giu nguyen (co nghia, ngan)
    """
    lab = (label or "").strip()
    lab_l = lab.lower()
    looks_url = (
        lab_l.startswith("http://")
        or lab_l.startswith("https://")
        or (" " not in lab and "/" in lab and "." in lab)
    )
    if (not lab) or looks_url or len(lab) > max_len:
        m = re.match(r"https?://([^/]+)", url)
        if m:
            return m.group(1)
        return (url[:max_len] + "…") if len(url) > max_len else url
    return lab


def render_email_html(
    html_body: str, max_len: int = 3500,
) -> tuple[str, list[tuple[str, str]]]:
    """Chuyen HTML email -> (telegram_html, links).

    - Giu link <a href> thanh link bam duoc (Telegram HTML parse_mode).
    - Tra ve danh sach (label, url) de tao nut mo webview trong Telegram.
    - AN TOAN: escape toan bo text truoc, chi chen lai the <a> hop le,
      nen khong bao gio gay loi "can't parse entities" cua Telegram.
    """
    import html as _htmlmod

    if not html_body:
        return "", []

    text = html_body

    # Bo hoan toan noi dung script/style
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", text)

    # Chuyen cac the khoi thanh xuong dong
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|tr|li|h[1-6]|table)>", "\n", text)
    text = re.sub(r"(?i)<(?:p|div|tr|li|h[1-6])[^>]*>", "\n", text)

    # Trich link <a href="...">text</a> -> placeholder de escape an toan
    links: list[tuple[str, str]] = []
    placeholders: dict[str, tuple[str, str]] = {}

    def _a_repl(m: "re.Match") -> str:
        url = (m.group("url") or "").strip()
        inner = m.group("inner") or ""
        label = re.sub(r"<[^>]+>", "", inner)          # bo tag long nhau
        label = _htmlmod.unescape(label).strip()
        # Rut gon nhan: URL dai -> ten mien
        display = short_link_label(label, url)
        idx = len(links)
        links.append((display, url))
        token = f"\x00A{idx}\x00"
        placeholders[token] = (url, display)
        return token

    text = re.sub(
        r'(?is)<a\b[^>]*\bhref\s*=\s*["\']?(?P<url>[^"\'>\s]+)["\']?[^>]*>'
        r'(?P<inner>.*?)</a>',
        _a_repl,
        text,
    )

    # Xoa cac the con lai
    text = re.sub(r"<[^>]+>", "", text)
    # Giai ma entity
    text = _htmlmod.unescape(text)
    # Gon khoang trang
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    # Cat bot cho vua Telegram (giu nguyen token neu con)
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "…"

    # Escape toan bo text (placeholder \x00A{idx}\x00 van ton tai)
    text = _htmlmod.escape(text)

    # Chen lai the <a> hop le
    for token, (url, label) in placeholders.items():
        if token not in text:
            continue  # bi cat mat -> bo qua (link van con o nut bam)
        safe_url = _htmlmod.escape(url, quote=True)
        safe_label = _htmlmod.escape(label) or safe_url
        text = text.replace(
            token, f'<a href="{safe_url}">{safe_label}</a>',
        )

    # Don placeholder du (neu bi cat doi)
    text = re.sub(r"\x00A?\d*\x00?", "", text)

    return text, links


def is_valid_code_value(code: str) -> bool:
    """Kiem tra gia tri co phai ma hop le khong."""
    cleaned = code.strip().lower()

    # Loai bo tu thuong gap
    if cleaned in COMMON_WORD_EXCLUSIONS:
        return False

    # Loai bo nam: 2020-2099
    if re.match(r"^20[2-9]\d$", cleaned):
        return False

    # Loai bo ngay thang: 01/01, 12/31, ...
    if re.match(r"^\d{1,2}[/\-]\d{1,2}(?:[/\-]\d{2,4})?$", cleaned):
        return False

    # Loai bo so qua ngan hoac qua dai
    digits_only = re.sub(r"\D", "", cleaned)
    if digits_only and (len(digits_only) < 4 or len(digits_only) > 8):
        # Nhung neu la ma hon hop chu-so thi cho phep
        if cleaned.isdigit():
            return False

    # Loai bo neu la chuoi chi gom 1 ky tu lap lai
    if len(set(cleaned.replace("-", "").replace(" ", ""))) <= 1:
        return False

    return True


def _find_code_near_keyword(text: str, keywords: list[str]) -> dict | None:
    """Tim ma gan tu khoa xac nhan."""
    text_lower = text.lower()
    for keyword in keywords:
        pos = text_lower.find(keyword)
        if pos == -1:
            continue
        # Lay doan van ban xung quanh tu khoa (100 ky tu truoc va sau)
        start = max(0, pos - 50)
        end = min(len(text), pos + len(keyword) + 100)
        context_text = text[start:end]

        # Tim ma trong vung ngu canh
        for match in CODE_PATTERN.finditer(context_text):
            candidate = match.group(0).strip()
            if is_valid_code_value(candidate):
                cleaned = clean_code_value(candidate)
                return {
                    "type": "code",
                    "value": cleaned,
                    "context": keyword,
                }
    return None


def find_best_code(subject: str, body: str, sender: str = None) -> dict | None:
    """
    Tim ma xac nhan tot nhat tu email.

    Returns {"type": "code", "value": "123456", "context": "..."} hoac None.
    """
    subject = subject or ""
    body = body or ""

    # Buoc 0: Lam sach body neu la HTML
    clean_body = _clean_html_to_text(body)

    full_text = f"{subject}\n{clean_body}"

    # Buoc 1: Kiem tra negative pattern — bo qua email khong phai xac nhan
    for pattern in NEGATIVE_PATTERNS:
        if pattern.search(subject):
            return None

    # Buoc 2: Thu pattern ngu canh truoc (do tin cay cao nhat)
    for pattern in CONTEXTUAL_PATTERNS:
        match = pattern.search(full_text)
        if match:
            candidate = match.group(1).strip()
            if is_valid_code_value(candidate):
                cleaned = clean_code_value(candidate)
                return {
                    "type": "code",
                    "value": cleaned,
                    "context": match.group(0).strip()[:80],
                }

    # Buoc 3: Neu email co tu khoa xac nhan, tim ma gan tu khoa
    text_lower = full_text.lower()
    has_verification_keyword = any(kw in text_lower for kw in VERIFICATION_KEYWORDS)

    if has_verification_keyword:
        result = _find_code_near_keyword(full_text, VERIFICATION_KEYWORDS)
        if result:
            return result

    return None


def extract_codes(subject: str, body: str, custom_pattern: str = None) -> list[dict]:
    """
    Trich xuat tat ca ma tu email.

    Returns danh sach code objects.
    """
    subject = subject or ""
    body = body or ""
    clean_body = _clean_html_to_text(body)
    full_text = f"{subject}\n{clean_body}"

    codes: list[dict] = []
    seen_values: set[str] = set()

    # Neu co custom pattern, dung no truoc
    if custom_pattern:
        try:
            custom_re = re.compile(custom_pattern)
            for match in custom_re.finditer(full_text):
                value = match.group(1) if match.lastindex else match.group(0)
                value = value.strip()
                cleaned = clean_code_value(value)
                if cleaned not in seen_values and is_valid_code_value(value):
                    seen_values.add(cleaned)
                    codes.append({
                        "type": "code",
                        "value": cleaned,
                        "context": f"custom: {match.group(0).strip()[:80]}",
                    })
        except re.error:
            pass

    # Tim bang contextual patterns
    for pattern in CONTEXTUAL_PATTERNS:
        for match in pattern.finditer(full_text):
            candidate = match.group(1).strip()
            cleaned = clean_code_value(candidate)
            if cleaned not in seen_values and is_valid_code_value(candidate):
                seen_values.add(cleaned)
                codes.append({
                    "type": "code",
                    "value": cleaned,
                    "context": match.group(0).strip()[:80],
                })

    # Tim bang CODE_PATTERN tong quat
    for match in CODE_PATTERN.finditer(full_text):
        candidate = match.group(0).strip()
        cleaned = clean_code_value(candidate)
        if cleaned not in seen_values and is_valid_code_value(candidate):
            seen_values.add(cleaned)
            codes.append({
                "type": "code",
                "value": cleaned,
                "context": full_text[max(0, match.start() - 20):match.end() + 20].strip()[:80],
            })

    return codes


def is_verification_email(subject: str, body_preview: str) -> bool:
    """Kiem tra email co phai la email xac nhan khong (heuristic)."""
    subject = (subject or "").lower()
    body_preview = (body_preview or "").lower()

    # Kiem tra negative patterns truoc
    for pattern in NEGATIVE_PATTERNS:
        if pattern.search(subject):
            return False

    combined = f"{subject} {body_preview}"
    match_count = sum(1 for kw in VERIFICATION_KEYWORDS if kw in combined)

    # Can it nhat 1 tu khoa va khong bi negative pattern
    return match_count >= 1
