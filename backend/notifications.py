"""Notification + reminder layer — VIen EMR native, no Google dependency.

In-portal notifications are immediate. Confirmation/reminder EMAILS are sent
directly via the Emergent-managed Resend integration. SMS/Twilio has been fully
removed: the only external channel is email. Detailed medical reasons are never
placed in external channel payloads.
"""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import email_service
import availability as avail_mod
from db import now_iso

logger = logging.getLogger("visita.notify")

CLINIC_TZ = ZoneInfo("America/Toronto")
PORTAL_URL = (os.environ.get("CORS_ORIGINS", "").split(",")[0] or "").strip().rstrip("/")
if not PORTAL_URL.startswith("http"):
    PORTAL_URL = ""
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


async def _in_portal(db, patient_id, title, body):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()), "patient_id": patient_id, "title": title,
        "body": body, "read": False, "created_at": now_iso(),
    })


async def _patient(db, patient_id):
    return await db.patients.find_one({"id": patient_id}, {"_id": 0})


def _time24(appt) -> str:
    t = appt.get("confirmed_slot_time")
    if not t:
        t = avail_mod._norm_time(appt.get("confirmed_time") or "")
    return t or ""


def _confirmed_dt_utc(appt):
    """Confirmed date+time (America/Toronto) as a UTC datetime, or None."""
    ds, t = appt.get("confirmed_date"), _time24(appt)
    if not ds or not t:
        return None
    try:
        h, m = t.split(":")
        local = datetime(*[int(x) for x in ds.split("-")], int(h), int(m), tzinfo=CLINIC_TZ)
        return local.astimezone(timezone.utc)
    except Exception:
        return None


def confirmed_dt_utc(appt):
    return _confirmed_dt_utc(appt)


def _type_label(appt) -> str:
    t = (appt or {}).get("appointment_type")
    if t == "TELEPHONE":
        return "Telephone Appointment"
    if t == "IN_CLINIC":
        return "In-Clinic Appointment"
    return "Not specified"


def _fmt_when(appt) -> str:
    """'2026 Sep - 23 at 1:30 PM' from confirmed date/time (America/Toronto)."""
    ds, t = appt.get("confirmed_date"), _time24(appt)
    if not ds:
        return appt.get("confirmed_display") or "your scheduled time"
    try:
        y, m, d = str(ds)[:10].split("-")
        base = f"{y} {_MONTHS[int(m) - 1]} - {d}"
    except Exception:
        return appt.get("confirmed_display") or str(ds)
    if t:
        try:
            h, mi = t.split(":")
            h = int(h)
            ampm = "AM" if h < 12 else "PM"
            return f"{base} at {h % 12 or 12}:{mi} {ampm}"
        except Exception:
            pass
    return base


async def _send_email(db, patient_id, to, subject, html):
    status = "prepared"
    if to:
        try:
            await email_service.send_email(to=to, subject=subject, html=html)
            status = "sent"
        except Exception as e:
            status = "failed"
            logger.warning(f"[email] send failed: {e}")
    await db.outbound_notifications.insert_one({
        "id": str(uuid.uuid4()), "channel": "email", "patient_id": patient_id,
        "to": to, "subject": subject, "status": status, "created_at": now_iso(),
    })
    return status


async def schedule_reminders(db, appt):
    """Create a 24h-before EMAIL reminder for a confirmed appointment.
    Idempotent: clears existing pending reminders for this appointment first."""
    await db.appointment_reminders.delete_many({"appointment_id": appt["id"], "delivery_status": "pending"})
    if appt.get("status") not in ("confirmed", "rescheduled"):
        return
    dt = _confirmed_dt_utc(appt)
    if not dt:
        return
    scheduled = (dt - timedelta(hours=24)).isoformat()
    await db.appointment_reminders.insert_one({
        "id": str(uuid.uuid4()), "appointment_id": appt["id"], "patient_id": appt.get("patient_id"),
        "reminder_type": "email", "scheduled_time": scheduled, "sent_time": None,
        "delivery_status": "pending", "created_at": now_iso(),
    })


async def cancel_reminders(db, appointment_id):
    await db.appointment_reminders.update_many(
        {"appointment_id": appointment_id, "delivery_status": "pending"},
        {"$set": {"delivery_status": "cancelled", "updated_at": now_iso()}})


async def appointment_confirmed(db, appt):
    p = await _patient(db, appt.get("patient_id"))
    first = (p or {}).get("first_name") or (appt.get("patient_name") or "").split(",")[-1].strip() or "there"
    when = _fmt_when(appt)
    disp = appt.get("confirmed_display") or when
    tlabel = _type_label(appt)
    await _in_portal(db, appt["patient_id"], "Appointment confirmed",
                     f"Your {tlabel} with Dr. Aguayo is confirmed for {disp}. See your Patient Portal for details.")
    email = (p or {}).get("email")
    html = email_service.appointment_confirmed_html(first, disp, PORTAL_URL, tlabel)
    await _send_email(db, appt["patient_id"], email, "Appointment Confirmed — Dr. Aguayo", html)
    await schedule_reminders(db, appt)


async def appointment_rescheduled(db, appt):
    p = await _patient(db, appt.get("patient_id"))
    first = (p or {}).get("first_name") or (appt.get("patient_name") or "").split(",")[-1].strip() or "there"
    when = _fmt_when(appt)
    disp = appt.get("confirmed_display") or when
    await _in_portal(db, appt["patient_id"], "Appointment rescheduled",
                     f"Your appointment with Dr. Aguayo has been rescheduled to {disp}. See your Patient Portal for details.")
    email = (p or {}).get("email")
    html = email_service.appointment_reschedule_html(first, disp, PORTAL_URL)
    await _send_email(db, appt["patient_id"], email, "Appointment Rescheduled — Dr. Aguayo", html)
    await schedule_reminders(db, appt)


async def appointment_cancelled(db, appt, reason=None):
    p = await _patient(db, appt.get("patient_id"))
    first = (p or {}).get("first_name") or "there"
    when = _fmt_when(appt)
    disp = appt.get("confirmed_display") or when
    note = f" Note: {reason}" if reason else ""
    await _in_portal(db, appt["patient_id"], "Appointment cancelled",
                     f"Your appointment with Dr. Aguayo scheduled for {disp} has been cancelled.{note} "
                     "Please contact the office if you have questions.")
    email = (p or {}).get("email")
    html = email_service.appointment_cancelled_html(first, disp, PORTAL_URL)
    await _send_email(db, appt["patient_id"], email, "Appointment Cancelled — Dr. Aguayo", html)
    await cancel_reminders(db, appt.get("id"))


async def account_verified(db, patient):
    """Patient registration verified/approved — in-portal + Resend email."""
    first = (patient or {}).get("first_name") or "there"
    pid = (patient or {}).get("id")
    await _in_portal(db, pid, "Account verified",
                     "Your VIen EMR patient portal account has been verified and is now active. "
                     "You can sign in to submit requests.")
    email = (patient or {}).get("email")
    html = email_service.account_verified_html(first, PORTAL_URL)
    await _send_email(db, pid, email, "Your VIen EMR account has been verified", html)


async def alternatives_offered(db, appt):
    msg = ("The appointment time you requested is not available. Dr. Aguayo's office has provided "
           "alternative appointment times. Please log in to your Patient Portal to choose one.")
    await _in_portal(db, appt["patient_id"], "Action needed: choose an appointment time", msg)


async def send_due_reminders(db):
    """Send all pending reminders whose scheduled_time has passed. Returns count sent."""
    now = datetime.now(timezone.utc).isoformat()
    due = await db.appointment_reminders.find(
        {"delivery_status": "pending", "scheduled_time": {"$lte": now}}).to_list(500)
    sent = 0
    for r in due:
        appt = await db.appointment_requests.find_one({"id": r["appointment_id"]}, {"_id": 0})
        if not appt or appt.get("status") not in ("confirmed", "rescheduled"):
            await db.appointment_reminders.update_one({"id": r["id"]}, {"$set": {"delivery_status": "cancelled"}})
            continue
        p = await _patient(db, r["patient_id"])
        disp = appt.get("confirmed_display") or f"{appt.get('confirmed_date')} {appt.get('confirmed_time')}"
        first = (p or {}).get("first_name") or "there"
        if r.get("reminder_type") != "email":
            # Legacy SMS reminders: Twilio has been removed. Cancel without sending.
            await db.appointment_reminders.update_one(
                {"id": r["id"]}, {"$set": {"delivery_status": "cancelled", "updated_at": now_iso()}})
            continue
        html = email_service.appointment_reminder_html(first, disp, PORTAL_URL)
        status = await _send_email(db, r["patient_id"], (p or {}).get("email"),
                                   "Appointment Reminder — Dr. Aguayo", html)
        await db.appointment_reminders.update_one({"id": r["id"]}, {"$set": {
            "delivery_status": status, "sent_time": now_iso()}})
        sent += 1
    return sent
