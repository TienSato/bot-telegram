"""Token ky (signed) cho webview xem mail.

Bot tao token chua (user_id, account_id, message_id), ky bang SECRET_KEY
va co han su dung. Trang web /mail/view/ giai ma + kiem han roi moi lay mail
phia server bang refresh_token (khong lo token ra client).
"""
from __future__ import annotations

from django.core import signing

SALT = "readmail.view"
DEFAULT_MAX_AGE = 1800  # 30 phut


def make_mail_token(user_id: int, account_id: int, message_id: str) -> str:
    """Tao token ky de mo webview mot mail."""
    return signing.dumps(
        {"u": user_id, "a": account_id, "m": message_id},
        salt=SALT,
    )


def read_mail_token(token: str, max_age: int = DEFAULT_MAX_AGE) -> dict:
    """Giai ma token. Raise signing.BadSignature / SignatureExpired neu loi."""
    return signing.loads(token, salt=SALT, max_age=max_age)
