"""Notification + calendar integration layer.

Version 1 delivers IN-PORTAL notifications immediately. Email / SMS are prepared
as an integration layer (queued to `outbound_notifications` with enabled=False)
so the clinic's existing Google Apps Script + Twilio + Email reminder system can
be connected later without changing callers. Detailed medical reasons are kept
OUT of external channel payloads.
"""
import logging
import uuid

from db import now_iso

logger = logging.getLogger("visita.notify")

# Toggle when the external integrations are wired up (kept off in V1).
CHANNELS = {"in_portal": True, "email": False, "sms": False}


async def _in_portal(db, patient_id, title, body):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "title": title,
        "body": body,
        "read": False,
        "created_at": now_iso(),
    })


async def _queue_external(db, channel, patient_id, subject, body):
    """Integration-layer placeholder for future Twilio/Email/Google workflow."""
    await db.outbound_notifications.insert_one({
        "id": str(uuid.uuid4()),
        "channel": channel,
        "patient_id": patient_id,
        "subject": subject,
        "body": body,
        "enabled": CHANNELS.get(channel, False),
        "status": "sent" if CHANNELS.get(channel) else "prepared",
        "created_at": now_iso(),
    })
    logger.info(f"[notify:{channel}] {'SENT' if CHANNELS.get(channel) else 'prepared (disabled)'} -> {patient_id}: {subject}")


def sync_calendar(appt, action):
    """Future Google Calendar sync (office hours - existing events - blocks).

    Intentionally a no-op stub until the clinic's Google Calendar / Apps Script
    system is provided. Do not implement assumptions about the Apps Script here.
    """
    logger.info(f"[calendar] TODO sync appointment={appt.get('id')} action={action}")


async def appointment_confirmed(db, appt):
    disp = appt.get("confirmed_display") or f"{appt.get('confirmed_date')} {appt.get('confirmed_time')}"
    ext = (f"Your appointment with Dr. Aguayo has been confirmed for {disp}. "
           "Please contact the clinic if you need to make any changes.")
    await _in_portal(db, appt["patient_id"], "Appointment confirmed",
                     "Your appointment has been confirmed. Please log in to your Patient Portal for details.")
    await _queue_external(db, "sms", appt["patient_id"], "Appointment Confirmed - Dr. Aguayo", ext)
    await _queue_external(db, "email", appt["patient_id"], "Appointment Confirmed – Dr. Aguayo", ext)
    sync_calendar(appt, "confirmed")


async def alternatives_offered(db, appt):
    msg = ("The appointment time you requested is not available. Dr. Aguayo's office has provided "
           "alternative appointment times. Please select the option that works best for you.")
    await _in_portal(db, appt["patient_id"], "Action needed: choose an appointment time", msg)
    await _queue_external(db, "sms", appt["patient_id"], "Appointment options available", msg)
