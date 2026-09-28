"""Emergent-managed email (Resend) — password reset codes only.

Recipients come from server-side user records and bodies from server-side
templates (never caller input). _assert_safe_email is the required G2/G3 gate.
"""
import ipaddress
import logging
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("visita.email")

EMAIL_BASE_URL = "https://integrations.emergentagent.com"  # constant on purpose (survives deploy)
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "VISITA")
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan(); scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        if not _host_ok(urlparse(low).hostname or "") or urlparse(low).username is not None:
            raise ValueError(f"Shortened/numeric/credential URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} != real host {real!r} (G3)")


async def send_email(*, to: str, subject: str, html: str) -> str | None:
    _assert_safe_email(subject, html)
    payload = {"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    if EMAIL_REPLY_TO:
        payload["contact_email"] = EMAIL_REPLY_TO
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": EMAIL_KEY},
                json=payload,
            )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:
        logger.error(f"Email send error: {e}")
        raise


def reset_code_html(name: str, code: str) -> str:
    safe_name = (name or "there").replace("<", "").replace(">", "")
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        f'<p>Hi {safe_name},</p>'
        '<p>We received a request to reset your VIsita EMR portal password. Use the verification code below to continue. '
        'It expires in 15 minutes.</p>'
        f'<p style="font-size:30px;font-weight:bold;letter-spacing:8px;background:#0b1524;color:#67e8f9;'
        f'padding:14px 20px;border-radius:6px;text-align:center;margin:16px 0">{code}</p>'
        '<p>If you did not request this, you can safely ignore this email and your password will stay the same.</p>'
        '<p style="font-size:12px;color:#888;margin-top:20px">Sent by VIsita EMR – Dr. Aguayo Family Practice. '
        'We will never ask you for your password by email.</p>'
        '</td></tr></table>'
    )


def _clean(s: str) -> str:
    return (s or "").replace("<", "").replace(">", "")


def _appt_email(heading: str, intro: str, name: str, when: str, portal_url: str, type_label: str = "") -> str:
    safe_name = _clean(name) or "there"
    when = _clean(when)
    type_label = _clean(type_label)
    link = ""
    if portal_url and portal_url.startswith("https://"):
        link = (f'<p style="margin:18px 0"><a href="{portal_url}/portal" '
                f'style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:6px;'
                f'text-decoration:none">Open Patient Portal</a></p>')
    type_row = ""
    if type_label:
        type_row = (f'<p style="font-size:14px;font-weight:bold;color:#0e7490;margin:0 0 14px">'
                    f'{type_label}</p>')
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        f'<h2 style="margin:0 0 12px">{heading}</h2>'
        f'<p>Hi {safe_name},</p><p>{intro}</p>'
        f'<p style="font-size:18px;font-weight:bold;background:#ecfeff;color:#0e7490;'
        f'padding:12px 16px;border-radius:6px;margin:14px 0 8px">{when}</p>'
        f'{type_row}'
        '<p><strong>Dr. Aguayo Family Practice</strong></p>'
        f'{link}'
        '<p style="font-size:12px;color:#888;margin-top:20px">Please contact the clinic if you need to reschedule '
        'or cancel. This message contains no medical information.</p>'
        '</td></tr></table>'
    )


def appointment_confirmed_html(name: str, when: str, portal_url: str = "", type_label: str = "") -> str:
    return _appt_email("Appointment Confirmed", "Your appointment with Dr. Aguayo has been confirmed for:",
                       name, when, portal_url, type_label)


def appointment_type_changed_html(name: str, when: str, portal_url: str = "", type_label: str = "") -> str:
    return _appt_email("Appointment Updated",
                       "The type of your appointment with Dr. Aguayo has been updated. Your date and time are unchanged:",
                       name, when, portal_url, type_label)


def appointment_reminder_html(name: str, when: str, portal_url: str = "") -> str:
    return _appt_email("Appointment Reminder", "This is a friendly reminder of your upcoming appointment with Dr. Aguayo:",
                       name, when, portal_url)


def appointment_reschedule_html(name: str, when: str, portal_url: str = "") -> str:
    return _appt_email("Appointment Rescheduled", "Your appointment with Dr. Aguayo has been rescheduled to:",
                       name, when, portal_url)


def appointment_cancelled_html(name: str, when: str, portal_url: str = "") -> str:
    return _appt_email("Appointment Cancelled", "Your appointment with Dr. Aguayo scheduled for the time below has been cancelled:",
                       name, when, portal_url)


def waiting_list_html(name: str) -> str:
    """Sent when an applicant is placed on the waiting list. No links/inputs — passes the gate."""
    safe_name = _clean(name) or "there"
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        '<h2 style="margin:0 0 12px">You\'ve been placed on the waiting list</h2>'
        f'<p>Hello {safe_name},</p>'
        '<p>Thank you for your interest in Dr. Aguayo\'s practice. Your request has been officially '
        'placed on our waiting list.</p>'
        '<p>Our office will contact you when a spot becomes available and let you know when you can '
        'book an appointment with the doctor. No further action is needed from you right now.</p>'
        '<p style="margin-top:16px"><strong>Dr. Aguayo\'s Office</strong><br>VIsita EMR</p>'
        '<p style="font-size:12px;color:#888;margin-top:20px">This message contains no medical information. '
        'We will never ask you for your password by email.</p>'
        '</td></tr></table>'
    )


def account_activation_html(name: str, activate_url: str) -> str:
    """New-patient acceptance + set-password activation link. `activate_url` must be
    an absolute https first-party portal URL (validated by _assert_safe_email)."""
    safe_name = _clean(name) or "there"
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        '<h2 style="margin:0 0 12px">You\'ve been accepted as a patient</h2>'
        f'<p>Hello {safe_name},</p>'
        '<p>Dr. Aguayo\'s office has accepted you as a patient and created your VIsita EMR '
        'patient portal account.</p>'
        '<p>To finish activating your portal, set your password using the secure button below. '
        'This link expires in 72 hours.</p>'
        f'<p style="margin:18px 0"><a href="{activate_url}" '
        'style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:6px;'
        'text-decoration:none">Set Your Password &amp; Activate Portal</a></p>'
        '<p style="margin-top:16px"><strong>Dr. Aguayo\'s Office</strong><br>VIsita EMR</p>'
        '<p style="font-size:12px;color:#888;margin-top:20px">If you did not expect this email you can '
        'safely ignore it. This message contains no medical information. '
        'We will never ask you for your password by email.</p>'
        '</td></tr></table>'
    )


def account_verified_html(name: str, portal_url: str = "") -> str:
    safe_name = _clean(name) or "there"
    link = ""
    if portal_url and portal_url.startswith("https://"):
        link = (f'<p style="margin:18px 0"><a href="{portal_url}/portal" '
                f'style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:6px;'
                f'text-decoration:none">Open Patient Portal</a></p>')
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        '<h2 style="margin:0 0 12px">Your account has been verified</h2>'
        f'<p>Hello {safe_name},</p>'
        '<p>Your registration with Dr. Aguayo\'s office has been verified and your VIsita EMR patient portal '
        'account is now active.</p>'
        '<p>You can now sign in to access the patient portal and submit requests.</p>'
        f'{link}'
        '<p style="margin-top:16px"><strong>Dr. Aguayo\'s Office</strong><br>VIsita EMR</p>'
        '<p style="font-size:12px;color:#888;margin-top:20px">This message contains no medical information. '
        'We will never ask you for your password by email.</p>'
        '</td></tr></table>'
    )
