"""Views — Read Mail Bot.

- setup_view: nguoi dau tien truy cap tao tai khoan admin.
- mail_view: webview xem mot mail (mo tu bot qua token ky, co han).
"""
from __future__ import annotations

import logging
import re

from django.contrib.auth import login
from django.contrib.auth.models import User
from django.core import signing
from django.shortcuts import redirect, render

logger = logging.getLogger(__name__)

_BASE_TAG_RE = re.compile(r"<base\b[^>]*>", re.IGNORECASE)
_BASE_HREF_RE = re.compile(r"""\bhref\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.IGNORECASE)
_HEAD_OPEN_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
_LINK_TAG_RE = re.compile(r"<(?:a|area|form)\b[^>]*>", re.IGNORECASE)
_TARGET_ATTR_RE = re.compile(
    r"""\s+target\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.IGNORECASE,
)


def _force_links_new_tab(html: str) -> str:
    """Moi link/nut trong mail mo o tab/cua so moi, khong load trong webview.

    Chen <base target="_blank"> vao HTML cua mail. Neu mail da co the <base>
    thi giu lai href cua no (link tuong doi van dung) nhung ep target=_blank.
    """
    if not html:
        return html
    href = ""
    m = _BASE_TAG_RE.search(html)
    if m:
        hm = _BASE_HREF_RE.search(m.group(0))
        if hm:
            href = hm.group(1).strip("\"'")
        html = _BASE_TAG_RE.sub("", html)
    # Bo target rieng cua tung link (_self/_top/_parent) de <base> ap dung.
    html = _LINK_TAG_RE.sub(
        lambda t: _TARGET_ATTR_RE.sub("", t.group(0)), html,
    )
    base = '<base target="_blank"'
    if href:
        base += ' href="' + href.replace('"', "&quot;") + '"'
    base += ">"
    hm = _HEAD_OPEN_RE.search(html)
    if hm:
        return html[:hm.end()] + base + html[hm.end():]
    return base + html


def setup_view(request):
    """Trang tao tai khoan admin — chi hien khi chua co user nao."""
    if User.objects.exists():
        return redirect("/admin/login/")

    error = ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")

        if not username or not password:
            error = "Vui lòng nhập đầy đủ thông tin."
        elif len(password) < 6:
            error = "Mật khẩu phải có ít nhất 6 ký tự."
        elif password != password2:
            error = "Mật khẩu nhập lại không khớp."
        else:
            user = User.objects.create_superuser(
                username=username,
                password=password,
            )
            login(request, user)
            return redirect("/admin/")

    return render(request, "setup.html", {"error": error})


def mail_view(request):
    """Webview xem mot mail. Xac thuc bang token ky (khong can dang nhap)."""
    from core.mailtoken import read_mail_token
    from core.models import MailAccount
    from features.readmail.graph_api import (
        exchange_refresh_token,
        get_message_detail,
    )

    token = request.GET.get("t", "")
    if not token:
        return render(request, "mail/view.html",
                      {"error": "Thiếu token."}, status=400)

    try:
        data = read_mail_token(token)
    except signing.SignatureExpired:
        return render(request, "mail/view.html",
                      {"error": "Link đã hết hạn. Quay lại bot và mở lại mail."},
                      status=403)
    except signing.BadSignature:
        return render(request, "mail/view.html",
                      {"error": "Token không hợp lệ."}, status=403)

    account = MailAccount.objects.filter(
        id=data.get("a"), user_id=data.get("u"),
    ).first()
    if account is None:
        return render(request, "mail/view.html",
                      {"error": "Không tìm thấy tài khoản."}, status=404)

    ok, token_info = exchange_refresh_token(
        account.refresh_token, account.client_id,
        account.tenant_id or "consumers",
    )
    if not ok:
        return render(request, "mail/view.html",
                      {"error": f"Đổi token thất bại: {token_info}",
                       "email": account.email}, status=502)

    ok2, detail = get_message_detail(
        token_info, data.get("m", ""), email_addr=account.email,
    )
    if not ok2:
        return render(request, "mail/view.html",
                      {"error": f"Đọc mail thất bại: {detail}",
                       "email": account.email}, status=502)

    code = ""
    code_info = detail.get("code")
    if code_info:
        code = str(code_info.get("value", ""))

    ctx = {
        "email": account.email,
        "subject": detail.get("subject", "(Không có tiêu đề)"),
        "from_name": detail.get("from_name", ""),
        "from_address": detail.get("from_address", ""),
        "date": detail.get("date", ""),
        "code": code,
        "content_type": (detail.get("content_type") or "text").lower(),
        "body_html": detail.get("html_body", "") or "",
    }
    if ctx["content_type"] == "html":
        ctx["body_html"] = _force_links_new_tab(ctx["body_html"])
    return render(request, "mail/view.html", ctx)
