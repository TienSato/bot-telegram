"""IMAP XOAUTH2 fallback — doc mail khi REST API that bai."""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import logging
import re

from features.readmail import code_extractor

logger = logging.getLogger(__name__)

IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993


def _build_xoauth2_string(user: str, token: str) -> str:
    """Tao chuoi XOAUTH2 de xac thuc IMAP."""
    auth_string = f"user={user}\x01auth=Bearer {token}\x01\x01"
    return auth_string


def _decode_mime_header(header_value: str) -> str:
    """Giai ma MIME header (RFC 2047)."""
    if not header_value:
        return ""
    decoded_parts = email.header.decode_header(header_value)
    result_parts = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                result_parts.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                result_parts.append(part.decode("utf-8", errors="replace"))
        else:
            result_parts.append(part)
    return " ".join(result_parts)


def _parse_date_to_iso(date_str: str) -> str:
    """Chuyen chuoi ngay trong email sang ISO format."""
    if not date_str:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        return parsed.isoformat()
    except Exception:
        return date_str


def _extract_text_from_message(msg: email.message.Message) -> tuple[str, str]:
    """
    Trich xuat noi dung text va HTML tu email message.

    Returns (text_body, html_body).
    """
    text_body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Bo qua attachment
            if "attachment" in content_disposition:
                continue

            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                continue

            if content_type == "text/plain":
                text_body = decoded
            elif content_type == "text/html":
                html_body = decoded
    else:
        content_type = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
                if content_type == "text/html":
                    html_body = decoded
                else:
                    text_body = decoded
        except Exception:
            pass

    return text_body, html_body


def _get_snippet(text_body: str, html_body: str, max_len: int = 200) -> str:
    """Tao doan trich ngan tu noi dung email."""
    if text_body:
        snippet = text_body.strip()
    elif html_body:
        snippet = code_extractor._clean_html_to_text(html_body)
    else:
        return ""
    # Cat va lam sach
    snippet = re.sub(r"\s+", " ", snippet).strip()
    if len(snippet) > max_len:
        snippet = snippet[:max_len] + "..."
    return snippet


def read_messages_imap(
    access_token: str, email_addr: str, limit: int = 10
) -> tuple[bool, list[dict] | str]:
    """
    Doc email qua IMAP XOAUTH2.

    Returns (success, messages_list | error_string).
    """
    imap = None
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)

        # Xac thuc XOAUTH2
        auth_string = _build_xoauth2_string(email_addr, access_token)
        imap.authenticate("XOAUTH2", lambda x: auth_string.encode())

        # Chon INBOX
        status, data = imap.select("INBOX", readonly=True)
        if status != "OK":
            return False, f"Khong the mo INBOX: {status}"

        # Tim tat ca message
        status, data = imap.search(None, "ALL")
        if status != "OK":
            return False, f"Khong the tim kiem: {status}"

        msg_ids = data[0].split()
        if not msg_ids:
            return True, []

        # Lay cac message moi nhat
        msg_ids = msg_ids[-limit:]
        msg_ids.reverse()  # Moi nhat truoc

        messages = []
        for msg_id_bytes in msg_ids:
            msg_id = msg_id_bytes.decode()
            try:
                # Lay header va phan dau cua body
                status, msg_data = imap.fetch(
                    msg_id_bytes, "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.2048>)"
                )
                if status != "OK" or not msg_data:
                    continue

                # Parse header
                header_data = None
                body_data = None
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        descriptor = response_part[0].decode("utf-8", errors="replace").upper()
                        if "HEADER" in descriptor:
                            header_data = response_part[1]
                        elif "TEXT" in descriptor:
                            body_data = response_part[1]

                if header_data is None:
                    continue

                msg = email.message_from_bytes(header_data)
                subject = _decode_mime_header(msg.get("Subject", ""))
                from_header = _decode_mime_header(msg.get("From", ""))
                date_str = msg.get("Date", "")

                # Parse from
                from_name, from_address = email.utils.parseaddr(from_header)
                from_name = from_name or from_address

                # Tao snippet tu body data
                snippet = ""
                if body_data:
                    try:
                        snippet = body_data.decode("utf-8", errors="replace")
                        snippet = code_extractor._clean_html_to_text(snippet)
                        snippet = re.sub(r"\s+", " ", snippet).strip()[:200]
                    except Exception:
                        snippet = ""

                # Tim ma xac nhan
                code_info = code_extractor.find_best_code(subject, snippet, from_address)

                messages.append({
                    "id": f"imap_{msg_id}",
                    "subject": subject,
                    "from_name": from_name,
                    "from_address": from_address,
                    "date": _parse_date_to_iso(date_str),
                    "snippet": snippet,
                    "code": code_info,
                })
            except Exception as e:
                logger.warning("IMAP: Loi khi doc message %s: %s", msg_id, e)
                continue

        return True, messages

    except imaplib.IMAP4.error as e:
        error_msg = str(e)
        logger.error("IMAP auth/connection error: %s", error_msg)
        return False, f"IMAP error: {error_msg}"
    except Exception as e:
        logger.error("IMAP unexpected error: %s", e)
        return False, f"IMAP error: {str(e)}"
    finally:
        if imap:
            try:
                imap.logout()
            except Exception:
                pass


def read_message_detail_imap(
    access_token: str, email_addr: str, message_id: str
) -> tuple[bool, dict | str]:
    """
    Doc chi tiet mot email qua IMAP.

    message_id co dang "imap_NNN" — can tach so NNN.
    Returns (success, detail_dict | error_string).
    """
    # Tach IMAP message number tu id
    imap_num = message_id
    if message_id.startswith("imap_"):
        imap_num = message_id[5:]

    imap = None
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)

        auth_string = _build_xoauth2_string(email_addr, access_token)
        imap.authenticate("XOAUTH2", lambda x: auth_string.encode())

        status, data = imap.select("INBOX", readonly=True)
        if status != "OK":
            return False, f"Khong the mo INBOX: {status}"

        # Lay toan bo message
        status, msg_data = imap.fetch(imap_num.encode(), "(RFC822)")
        if status != "OK" or not msg_data:
            return False, f"Khong tim thay message: {message_id}"

        raw_email = None
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                raw_email = response_part[1]
                break

        if raw_email is None:
            return False, f"Khong the doc noi dung message: {message_id}"

        msg = email.message_from_bytes(raw_email)
        subject = _decode_mime_header(msg.get("Subject", ""))
        from_header = _decode_mime_header(msg.get("From", ""))
        date_str = msg.get("Date", "")
        from_name, from_address = email.utils.parseaddr(from_header)
        from_name = from_name or from_address

        text_body, html_body = _extract_text_from_message(msg)
        snippet = _get_snippet(text_body, html_body)

        # Xac dinh content type va body hien thi
        if html_body:
            content_type = "html"
            display_body = html_body
        else:
            content_type = "text"
            display_body = text_body

        code_info = code_extractor.find_best_code(subject, snippet, from_address)

        return True, {
            "id": message_id,
            "subject": subject,
            "from_name": from_name,
            "from_address": from_address,
            "date": _parse_date_to_iso(date_str),
            "snippet": snippet,
            "html_body": display_body,
            "content_type": content_type,
            "code": code_info,
        }

    except imaplib.IMAP4.error as e:
        logger.error("IMAP detail error: %s", e)
        return False, f"IMAP error: {str(e)}"
    except Exception as e:
        logger.error("IMAP detail unexpected error: %s", e)
        return False, f"IMAP error: {str(e)}"
    finally:
        if imap:
            try:
                imap.logout()
            except Exception:
                pass
