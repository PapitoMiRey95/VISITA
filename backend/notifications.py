"""Notification + reminder layer — VIen EMR native, no Google dependency.

In-portal notifications are immediate. Confirmation/reminder EMAILS are sent
directly via the Emergent-managed Resend integration. SMS is sent directly via
Twilio when credentials are configured, otherwise it is recorded as "prepared"
and skipped gracefully. Detailed medical reasons are never placed in external
channel payloads.
"""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import email_service
from db import now_iso

logger = logging.getLogger("visita.notify")

CLINIC_TZ = ZoneInfo("America/Toronto")
PORTAL_URL = (os.environ.get("CORS_ORIGINS", "").split(",")[0] or "").strip().rstrip("/")
TWILIO_ENABLED = bool(os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN")
                      and os.environ.get("TWILIO_FROM_NUMBER"))


async def _in_portal(db, patient_id, title, body):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()), "patient_id": patient_id, "title": title,
        "body": body, "read": False, "created_at": now_iso(),
    })


async def _patient(db, patient_id):
    return await db.patients.find_one({"id": patient_id}, {"_id": 0})


def _confirmed_dt_utc(appt):
    """Confirmed date+time (America/Toronto) as a UTC datetime, or None."""
    ds, t = appt.get("confirmed_date"), (appt.get("confirmed_slot_time") or "")
    if not ds:
        return None
    if not t:
        return None
    try:
        h, m = t.split(":")
        local = datetime(*[int(x) for x in ds.split("-")], int(h), int(m), tzinfo=CLINIC_TZ)
        return local.astimezone(timezone.utc)
    except Exception:
        return None


async def _send_sms(db, patient_id, phone, body):
    """Direct Twilio when configured; otherwise record as prepared and skip."""
    status = "prepared"
    if TWILIO_ENABLED and phone:
        try:
            from twilio.rest import Client  # optional dependency
            client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
            client.messages.create(to=phone, from_=os.environ["TWILIO_FROM_NUMBER"], body=body)
            status = "sent"
        except Exception as e:
            status = "failed"
            logger.warning(f"[sms] send failed: {e}")
    await db.outbound_notifications.insert_one({
        "id": str(uuid.uuid4()), "channel": "sms", "patient_id": patient_id,
        "to": phone, "body": body, "status": status, "created_at": now_iso(),
    })
    return status


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
    """Create 24h-before email + sms reminders for a confirmed appointment.
    Idempotent: clears existing pending reminders for this appointment first."""
    await db.appointment_reminders.delete_many({"appointment_id": appt["id"], "delivery_status": "pending"})
    if appt.get("status") not in ("confirmed", "rescheduled"):
        return
    dt = _confirmed_dt_utc(appt)
    if not dt:
        return
    scheduled = (dt - timedelta(hours=24)).isoformat()
    for rtype in ("email", "sms"):
        await db.appointment_reminders.insert_one({
            "id": str(uuid.uuid4()), "appointment_id": appt["id"], "patient_id": appt.get("patient_id"),
            "reminder_type": rtype, "scheduled_time": scheduled, "sent_time": None,
            "delivery_status": "pending", "created_at": now_iso(),
        })


async def cancel_reminders(db, appointment_id):
    await db.appointment_reminders.update_many(
        {"appointment_id": appointment_id, "delivery_status": "pending"},
        {"$set": {"delivery_status": "cancelled", "updated_at": now_iso()}})


async def appointment_confirmed(db, appt):
    p = await _patient(db, appt.get("patient_id"))
    first = (p or {}).get("first_name") or (appt.get("patient_name") or "").split(",")[-1].strip() or "there"
    disp = appt.get("confirmed_display") or f"{appt.get('confirmed_date')} {appt.get('confirmed_time')}"
    await _in_portal(db, appt["patient_id"], "Appointment confirmed",
                     f"Your appointment with Dr. Aguayo is confirmed for {disp}. See your Patient Portal for details.")
    email = (p or {}).get("email")
    phone = (p or {}).get("phone")
    html = email_service.appointment_confirmed_html(first, disp, PORTAL_URL)
    await _send_email(db, appt["patient_id"], email, "Appointment Confirmed — Dr. Aguayo", html)
    await _send_sms(db, appt["patient_id"], phone,
                    f"Appointment Confirmed with Dr. Aguayo for {disp}. Details: {PORTAL_URL}/portal")
    await schedule_reminders(db, appt)


async def alternatives_offered(db, appt):
    msg = ("The appointment time you requested is not available. Dr. Aguayo's office has provided "
           "alternative appointment times. Please log in to your Patient Portal to choose one.")
    await _in_portal(db, appt["patient_id"], "Action needed: choose an appointment time", msg)
    p = await _patient(db, appt.get("patient_id"))
    await _send_sms(db, appt["patient_id"], (p or {}).get("phone"), msg)


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
        if r["reminder_type"] == "email":
            html = email_service.appointment_reminder_html(first, disp, PORTAL_URL)
            status = await _send_email(db, r["patient_id"], (p or {}).get("email"),
                                       "Appointment Reminder — Dr. Aguayo", html)
        else:
            status = await _send_sms(db, r["patient_id"], (p or {}).get("phone"),
                                     f"Reminder: appointment with Dr. Aguayo {disp}. {PORTAL_URL}/portal")
        await db.appointment_reminders.update_one({"id": r["id"]}, {"$set": {
            "delivery_status": status, "sent_time": now_iso()}})
        sent += 1
    return sent
