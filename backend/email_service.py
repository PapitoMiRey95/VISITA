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


def norm_lang(lang) -> str:
    """Only EN/ES are enabled for patient emails; everything else falls back to English."""
    return "es" if str(lang or "").lower().startswith("es") else "en"


# Localized subject lines for system-generated patient emails.
SUBJECTS = {
    "account_verified": {"en": "Your Patient Portal account has been verified",
                         "es": "Su cuenta del Portal del Paciente ha sido verificada"},
    "account_activation": {"en": "You've been accepted — activate your Patient Portal",
                           "es": "Ha sido aceptado — active su Portal del Paciente"},
    "reset_code": {"en": "Your Patient Portal password reset code",
                   "es": "Su código para restablecer la contraseña del Portal del Paciente"},
    "appt_confirmed": {"en": "Appointment Confirmed — Dr. Aguayo",
                       "es": "Cita confirmada — Dr. Aguayo"},
    "appt_type_changed": {"en": "Appointment Update — Dr. Aguayo",
                          "es": "Actualización de su cita — Dr. Aguayo"},
    "appt_reminder": {"en": "Appointment Reminder — Dr. Aguayo",
                      "es": "Recordatorio de cita — Dr. Aguayo"},
    "appt_rescheduled": {"en": "Appointment Rescheduled — Dr. Aguayo",
                         "es": "Cita reprogramada — Dr. Aguayo"},
    "appt_cancelled": {"en": "Appointment Cancelled — Dr. Aguayo",
                       "es": "Cita cancelada — Dr. Aguayo"},
    "waiting_list": {"en": "You've been placed on the waiting list",
                     "es": "Ha sido colocado en la lista de espera"},
    "invoice_issued": {"en": "New invoice from Dr. Aguayo's office",
                       "es": "Nueva factura del consultorio del Dr. Aguayo"},
}

# Shared chrome strings (never contain patient/clinical free text).
_CHROME = {
    "greet": {"en": "Hi {n},", "es": "Hola {n},"},
    "hello": {"en": "Hello {n},", "es": "Hola {n},"},
    "open_portal": {"en": "Open Patient Portal", "es": "Abrir el Portal del Paciente"},
    "office": {"en": "Dr. Aguayo's Office", "es": "Consultorio del Dr. Aguayo"},
    "no_medical": {"en": "This message contains no medical information. We will never ask you for your password by email.",
                   "es": "Este mensaje no contiene información médica. Nunca le pediremos su contraseña por correo electrónico."},
    "appt_footer": {"en": "Please contact the clinic if you need to reschedule or cancel. This message contains no medical information.",
                    "es": "Si necesita reprogramar o cancelar, comuníquese con el consultorio. Este mensaje no contiene información médica."},
}
_DEFAULT_NAME = {"en": "there", "es": "paciente"}


def subject(key: str, lang="en") -> str:
    return SUBJECTS[key][norm_lang(lang)]


def _clean(s: str) -> str:
    return (s or "").replace("<", "").replace(">", "")


def reset_code_html(name: str, code: str, lang="en") -> str:
    L = norm_lang(lang)
    safe_name = _clean(name) or _DEFAULT_NAME[L]
    greet = _CHROME["greet"][L].format(n=safe_name)
    intro = ("We received a request to reset your Patient Portal password. Use the verification code below to continue. "
             "It expires in 15 minutes." if L == "en" else
             "Recibimos una solicitud para restablecer la contraseña de su Portal del Paciente. Use el código de "
             "verificación a continuación para continuar. Expira en 15 minutos.")
    ignore = ("If you did not request this, you can safely ignore this email and your password will stay the same."
              if L == "en" else
              "Si no solicitó esto, puede ignorar este correo de forma segura y su contraseña no cambiará.")
    footer = ("Sent by VIsita EMR – Dr. Aguayo Family Practice. We will never ask you for your password by email."
              if L == "en" else
              "Enviado por VIsita EMR – Dr. Aguayo Family Practice. Nunca le pediremos su contraseña por correo electrónico.")
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        f'<p>{greet}</p>'
        f'<p>{intro}</p>'
        f'<p style="font-size:30px;font-weight:bold;letter-spacing:8px;background:#0b1524;color:#67e8f9;'
        f'padding:14px 20px;border-radius:6px;text-align:center;margin:16px 0">{code}</p>'
        f'<p>{ignore}</p>'
        f'<p style="font-size:12px;color:#888;margin-top:20px">{footer}</p>'
        '</td></tr></table>'
    )


def _appt_email(heading: str, intro: str, name: str, when: str, portal_url: str, type_label: str = "", lang="en") -> str:
    L = norm_lang(lang)
    safe_name = _clean(name) or _DEFAULT_NAME[L]
    when = _clean(when)
    type_label = _clean(type_label)
    greet = _CHROME["greet"][L].format(n=safe_name)
    link = ""
    if portal_url and portal_url.startswith("https://"):
        link = (f'<p style="margin:18px 0"><a href="{portal_url}/portal" '
                f'style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:6px;'
                f'text-decoration:none">{_CHROME["open_portal"][L]}</a></p>')
    type_row = ""
    if type_label:
        type_row = (f'<p style="font-size:14px;font-weight:bold;color:#0e7490;margin:0 0 14px">'
                    f'{type_label}</p>')
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        f'<h2 style="margin:0 0 12px">{heading}</h2>'
        f'<p>{greet}</p><p>{intro}</p>'
        f'<p style="font-size:18px;font-weight:bold;background:#ecfeff;color:#0e7490;'
        f'padding:12px 16px;border-radius:6px;margin:14px 0 8px">{when}</p>'
        f'{type_row}'
        '<p><strong>Dr. Aguayo Family Practice</strong></p>'
        f'{link}'
        f'<p style="font-size:12px;color:#888;margin-top:20px">{_CHROME["appt_footer"][L]}</p>'
        '</td></tr></table>'
    )


_APPT_COPY = {
    "confirmed": {"en": ("Appointment Confirmed", "Your appointment with Dr. Aguayo has been confirmed for:"),
                  "es": ("Cita confirmada", "Su cita con el Dr. Aguayo ha sido confirmada para:")},
    "type_changed": {"en": ("Appointment Updated", "The type of your appointment with Dr. Aguayo has been updated. Your date and time are unchanged:"),
                     "es": ("Cita actualizada", "El tipo de su cita con el Dr. Aguayo ha sido actualizado. La fecha y la hora no cambian:")},
    "reminder": {"en": ("Appointment Reminder", "This is a friendly reminder of your upcoming appointment with Dr. Aguayo:"),
                 "es": ("Recordatorio de cita", "Este es un recordatorio de su próxima cita con el Dr. Aguayo:")},
    "reschedule": {"en": ("Appointment Rescheduled", "Your appointment with Dr. Aguayo has been rescheduled to:"),
                   "es": ("Cita reprogramada", "Su cita con el Dr. Aguayo ha sido reprogramada para:")},
    "cancelled": {"en": ("Appointment Cancelled", "Your appointment with Dr. Aguayo scheduled for the time below has been cancelled:"),
                  "es": ("Cita cancelada", "Su cita con el Dr. Aguayo programada para la fecha indicada ha sido cancelada:")},
}


def appointment_confirmed_html(name: str, when: str, portal_url: str = "", type_label: str = "", lang="en") -> str:
    h, i = _APPT_COPY["confirmed"][norm_lang(lang)]
    return _appt_email(h, i, name, when, portal_url, type_label, lang)


def appointment_type_changed_html(name: str, when: str, portal_url: str = "", type_label: str = "", lang="en") -> str:
    h, i = _APPT_COPY["type_changed"][norm_lang(lang)]
    return _appt_email(h, i, name, when, portal_url, type_label, lang)


def appointment_reminder_html(name: str, when: str, portal_url: str = "", lang="en") -> str:
    h, i = _APPT_COPY["reminder"][norm_lang(lang)]
    return _appt_email(h, i, name, when, portal_url, lang=lang)


def appointment_reschedule_html(name: str, when: str, portal_url: str = "", lang="en") -> str:
    h, i = _APPT_COPY["reschedule"][norm_lang(lang)]
    return _appt_email(h, i, name, when, portal_url, lang=lang)


def appointment_cancelled_html(name: str, when: str, portal_url: str = "", lang="en") -> str:
    h, i = _APPT_COPY["cancelled"][norm_lang(lang)]
    return _appt_email(h, i, name, when, portal_url, lang=lang)


def waiting_list_html(name: str, lang="en") -> str:
    """Sent when an applicant is placed on the waiting list. No links/inputs — passes the gate."""
    L = norm_lang(lang)
    safe_name = _clean(name) or _DEFAULT_NAME[L]
    hello = _CHROME["hello"][L].format(n=safe_name)
    if L == "es":
        heading = "Ha sido colocado en la lista de espera"
        p1 = ("Gracias por su interés en el consultorio del Dr. Aguayo. Su solicitud ha sido colocada "
              "oficialmente en nuestra lista de espera.")
        p2 = ("Nuestro consultorio se comunicará con usted cuando haya un lugar disponible y le informará "
              "cuándo podrá reservar una cita con el doctor. No necesita hacer nada más por ahora.")
    else:
        heading = "You've been placed on the waiting list"
        p1 = ("Thank you for your interest in Dr. Aguayo's practice. Your request has been officially "
              "placed on our waiting list.")
        p2 = ("Our office will contact you when a spot becomes available and let you know when you can "
              "book an appointment with the doctor. No further action is needed from you right now.")
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        f'<h2 style="margin:0 0 12px">{heading}</h2>'
        f'<p>{hello}</p>'
        f'<p>{p1}</p><p>{p2}</p>'
        f'<p style="margin-top:16px"><strong>{_CHROME["office"][L]}</strong><br>VIsita EMR</p>'
        f'<p style="font-size:12px;color:#888;margin-top:20px">{_CHROME["no_medical"][L]}</p>'
        '</td></tr></table>'
    )


def account_activation_html(name: str, activate_url: str, lang="en") -> str:
    """New-patient acceptance + set-password activation link. `activate_url` must be
    an absolute https first-party portal URL (validated by _assert_safe_email)."""
    L = norm_lang(lang)
    safe_name = _clean(name) or _DEFAULT_NAME[L]
    hello = _CHROME["hello"][L].format(n=safe_name)
    if L == "es":
        heading = "Ha sido aceptado como paciente"
        p1 = "El consultorio del Dr. Aguayo lo ha aceptado como paciente y ha creado su cuenta del Portal del Paciente."
        p2 = ("Para terminar de activar su portal, establezca su contraseña con el botón seguro a continuación. "
              "Este enlace expira en 72 horas.")
        btn = "Establecer contraseña y activar el portal"
        ignore = ("Si no esperaba este correo, puede ignorarlo de forma segura. " + _CHROME["no_medical"]["es"])
    else:
        heading = "You've been accepted as a patient"
        p1 = "Dr. Aguayo's office has accepted you as a patient and created your Patient Portal account."
        p2 = ("To finish activating your portal, set your password using the secure button below. "
              "This link expires in 72 hours.")
        btn = "Set Your Password &amp; Activate Portal"
        ignore = ("If you did not expect this email you can safely ignore it. " + _CHROME["no_medical"]["en"])
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        f'<h2 style="margin:0 0 12px">{heading}</h2>'
        f'<p>{hello}</p>'
        f'<p>{p1}</p>'
        f'<p>{p2}</p>'
        f'<p style="margin:18px 0"><a href="{activate_url}" '
        'style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:6px;'
        f'text-decoration:none">{btn}</a></p>'
        f'<p style="margin-top:16px"><strong>{_CHROME["office"][L]}</strong><br>VIsita EMR</p>'
        f'<p style="font-size:12px;color:#888;margin-top:20px">{ignore}</p>'
        '</td></tr></table>'
    )


def account_verified_html(name: str, portal_url: str = "", lang="en") -> str:
    L = norm_lang(lang)
    safe_name = _clean(name) or _DEFAULT_NAME[L]
    hello = _CHROME["hello"][L].format(n=safe_name)
    link = ""
    if portal_url and portal_url.startswith("https://"):
        link = (f'<p style="margin:18px 0"><a href="{portal_url}/portal" '
                f'style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:6px;'
                f'text-decoration:none">{_CHROME["open_portal"][L]}</a></p>')
    if L == "es":
        heading = "Su cuenta del Portal del Paciente ha sido verificada"
        p1 = ("Su registro con el consultorio del Dr. Aguayo ha sido verificado y su cuenta del Portal del "
              "Paciente ya está activa.")
        p2 = "Ahora puede iniciar sesión para acceder al Portal del Paciente y enviar solicitudes."
    else:
        heading = "Your Patient Portal account has been verified"
        p1 = ("Your registration with Dr. Aguayo's office has been verified and your Patient Portal account "
              "is now active.")
        p2 = "You can now sign in to access the Patient Portal and submit requests."
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        f'<h2 style="margin:0 0 12px">{heading}</h2>'
        f'<p>{hello}</p>'
        f'<p>{p1}</p>'
        f'<p>{p2}</p>'
        f'{link}'
        f'<p style="margin-top:16px"><strong>{_CHROME["office"][L]}</strong><br>VIsita EMR</p>'
        f'<p style="font-size:12px;color:#888;margin-top:20px">{_CHROME["no_medical"][L]}</p>'
        '</td></tr></table>'
    )


def invoice_issued_html(name: str, amount_display: str, portal_url: str = "", lang="en") -> str:
    """Net-new: notifies a patient that a new invoice is available in the portal.
    amount_display is a preformatted currency string (e.g. '$45.00') — not translated."""
    L = norm_lang(lang)
    safe_name = _clean(name) or _DEFAULT_NAME[L]
    amount_display = _clean(amount_display)
    hello = _CHROME["hello"][L].format(n=safe_name)
    link = ""
    if portal_url and portal_url.startswith("https://"):
        label = "Ver factura en el portal" if L == "es" else "View invoice in the portal"
        link = (f'<p style="margin:18px 0"><a href="{portal_url}/portal/invoices" '
                f'style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:6px;'
                f'text-decoration:none">{label}</a></p>')
    if L == "es":
        heading = "Nueva factura disponible"
        p1 = "El consultorio del Dr. Aguayo ha emitido una nueva factura en su Portal del Paciente."
        amt_label = "Monto"
        p2 = "Puede ver los detalles y las opciones de pago en el Portal del Paciente."
    else:
        heading = "New invoice available"
        p1 = "Dr. Aguayo's office has issued a new invoice on your Patient Portal."
        amt_label = "Amount"
        p2 = "You can view the details and payment options in the Patient Portal."
    amt_row = ""
    if amount_display:
        amt_row = (f'<p style="font-size:18px;font-weight:bold;background:#ecfeff;color:#0e7490;'
                   f'padding:12px 16px;border-radius:6px;margin:14px 0 8px">{amt_label}: {amount_display}</p>')
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
        f'<h2 style="margin:0 0 12px">{heading}</h2>'
        f'<p>{hello}</p>'
        f'<p>{p1}</p>'
        f'{amt_row}'
        f'<p>{p2}</p>'
        f'{link}'
        f'<p style="margin-top:16px"><strong>{_CHROME["office"][L]}</strong><br>VIsita EMR</p>'
        f'<p style="font-size:12px;color:#888;margin-top:20px">{_CHROME["no_medical"][L]}</p>'
        '</td></tr></table>'
    )
