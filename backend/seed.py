import os
import uuid

import availability as avail_mod
import storage
from db import next_ref, now_iso


def make_pdf(lines):
    """Build a tiny but valid single-page PDF from text lines."""
    text_ops = "BT /F1 14 Tf 40 740 Td 18 TL "
    for ln in lines:
        safe = ln.replace("(", "").replace(")", "").encode("latin-1", "ignore").decode("latin-1")
        text_ops += f"({safe}) Tj T* "
    text_ops += "ET"
    objects = [
        "<</Type/Catalog/Pages 2 0 R>>",
        "<</Type/Pages/Kids[3 0 R]/Count 1>>",
        "<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        f"<</Length {len(text_ops)}>>\nstream\n{text_ops}\nendstream",
        "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    pdf = "%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf.encode("latin-1")))
        pdf += f"{i} 0 obj\n{obj}\nendobj\n"
    xref_pos = len(pdf.encode("latin-1"))
    pdf += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n"
    pdf += f"trailer\n<</Size {len(objects)+1}/Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF"
    return pdf.encode("latin-1")


DEFAULT_TEMPLATES = {
    "smart_routing_intro": "What can we help you with?",
    "prescription_received": "Your prescription request has been received.",
    "referral_delay": ("Your referral request has been received and is currently pending physician review. "
                       "Some requests require additional review or administrative processing before they can be "
                       "completed. Thank you for your patience. No further action is required from you at this time."),
    "new_referral_notice": ("A medical appointment may be required before a new referral can be issued. "
                            "Please request an appointment and we will follow up with you."),
    "appointment_required": "Based on your request, an appointment with the clinic is required. Please request an appointment.",
    "emergency_notice": ("This portal is not monitored continuously and should not be used for emergencies. "
                         "If you are experiencing a medical emergency, call 911 or go to the nearest Emergency Department."),
    "portal_disclaimer": "This portal is for non-urgent requests and communication with the clinic.",
}

DEFAULT_SETTINGS = {
    "id": "clinic",
    "clinic_name": "VISITA — Dr. Aguayo Family Practice",
    "physician_name": "Dr. Pablo Aguayo",
    "clinic_phone": "(647) 555-0123",
    "clinic_address": "1031 Dovercourt Rd, Toronto, ON M6H 2X7",
    "office_hours": "Mon–Fri 9:00 AM – 5:00 PM",
}


async def _make_patient(db, authlib, first, last, dob, ptype, phone, email,
                        hcn=None, province=None, country=None, verified=True, extra=None):
    pid = str(uuid.uuid4())
    await db.patients.insert_one({
        "id": pid, "visita_patient_id": None, "first_name": first, "last_name": last,
        "date_of_birth": dob, "health_card_number": hcn, "health_card_version": None,
        "phone": phone, "email": email.lower(), "province": province, "country": country,
        "extra_info": extra, "patient_type": ptype,
        "verification_status": "verified" if verified else "pending",
        "active_status": True, "is_demo": True, "created_at": now_iso(), "updated_at": now_iso(),
    })
    await db.users.insert_one({
        "email": email.lower(), "password_hash": authlib.hash_password("Patient2026!"),
        "name": f"{first} {last}", "role": "patient", "patient_id": pid,
        "active": True, "created_at": now_iso(),
    })
    return pid


async def seed_all(db, authlib):
    # 1. Owner/admin (always ensured)
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
    admin_pw = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "email": admin_email, "password_hash": authlib.hash_password(admin_pw),
            "name": "Kevin Rodriguez", "role": "admin", "patient_id": None,
            "active": True, "created_at": now_iso(),
        })
    elif not authlib.verify_password(admin_pw, existing["password_hash"]):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": authlib.hash_password(admin_pw)}})

    # settings & templates
    if not await db.settings.find_one({"id": "clinic"}):
        await db.settings.insert_one({**DEFAULT_SETTINGS})
    if not await db.templates.find_one({"id": "templates"}):
        await db.templates.insert_one({"id": "templates", "items": DEFAULT_TEMPLATES})
    if not await db.settings.find_one({"id": "availability"}):
        await db.settings.insert_one({**avail_mod.DEFAULT_AVAILABILITY})

    # one-time migration: give legacy appointment requests slot-based options
    if not await db.app_meta.find_one({"id": "appt_v2"}):
        avail = await db.settings.find_one({"id": "availability"}, {"_id": 0}) or avail_mod.DEFAULT_AVAILABILITY
        slots = avail_mod.generate_slots(avail, days=21)
        legacy = await db.appointment_requests.find({"preferred_options": {"$exists": False}}).to_list(500)
        for idx, a in enumerate(legacy):
            picks = slots[idx * 2: idx * 2 + 3] if slots else []
            if not picks and slots:
                picks = slots[:3]
            opt1 = picks[0] if picks else {"date": a.get("preferred_date"), "time": "11:30",
                                           "label": "11:30 AM", "display": f"{a.get('preferred_date')} 11:30 AM"}
            await db.appointment_requests.update_one({"id": a["id"]}, {"$set": {
                "preferred_options": picks or [opt1],
                "offered_slots": a.get("offered_slots", []),
                "selected_slot": None,
                "confirmed_date": None, "confirmed_time": None, "confirmed_display": None,
                "approved_by": None, "approved_at": None,
                "preferred_date": opt1.get("date"), "preferred_time": opt1.get("label"),
            }})
        await db.app_meta.insert_one({"id": "appt_v2", "at": now_iso()})

    # physician account: username login + forced temp-password change (one-time)
    if not await db.app_meta.find_one({"id": "phys_v2"}):
        uname = os.environ.get("PHYSICIAN_USERNAME", "PAGUAYO")
        temp = os.environ.get("PHYSICIAN_TEMP_PASSWORD", "ChangeMe#2026")
        phys = await db.users.find_one({"role": "physician"})
        payload = {
            "username": uname, "name": "Dr. Pablo Aguayo", "role": "physician",
            "password_hash": authlib.hash_password(temp), "must_change_password": True,
            "mfa_enabled": False, "patient_id": None, "active": True,
        }
        if phys:
            await db.users.update_one({"_id": phys["_id"]}, {"$set": payload})
        else:
            payload["email"] = "doctor@visita.demo"
            payload["created_at"] = now_iso()
            await db.users.insert_one(payload)
        await db.app_meta.insert_one({"id": "phys_v2", "at": now_iso()})

    # guard demo
    if await db.app_meta.find_one({"id": "seeded_v1"}):
        return

    # 2. Staff & physician accounts
    for email, name, role, pw in [
        ("staff@visita.demo", "Kevin (Front Desk)", "staff", "Staff2026!"),
        ("doctor@visita.demo", "Dr. Pablo Aguayo", "physician", "Doctor2026!"),
    ]:
        if not await db.users.find_one({"email": email}):
            await db.users.insert_one({
                "email": email, "password_hash": authlib.hash_password(pw), "name": name,
                "role": role, "patient_id": None, "active": True, "created_at": now_iso(),
            })

    # 3. Pharmacies
    pharmacies = [
        {"id": str(uuid.uuid4()), "name": "Shoppers Drug Mart — Dovercourt", "address": "1234 Dovercourt Rd, Toronto", "fax": "(416) 555-1000", "phone": "(416) 555-1001"},
        {"id": str(uuid.uuid4()), "name": "Rexall — Bloor St", "address": "500 Bloor St W, Toronto", "fax": "(416) 555-2000", "phone": "(416) 555-2001"},
    ]
    await db.pharmacies.insert_many([{**p} for p in pharmacies])

    # 4. Verified demo patients
    maria = await _make_patient(db, authlib, "Maria", "Lopez", "1972-03-14", "ohip", "(416) 555-3011", "maria.lopez@demo.com", hcn="1234-567-890-AB", province="ON")
    john = await _make_patient(db, authlib, "John", "Smith", "1985-07-22", "ohip", "(416) 555-3022", "john.smith@demo.com", hcn="2345-678-901-CD", province="ON")
    carlos = await _make_patient(db, authlib, "Carlos", "Perez", "1990-11-02", "ohip", "(416) 555-3033", "carlos.perez@demo.com", hcn="3456-789-012-EF", province="ON")
    linda = await _make_patient(db, authlib, "Linda", "Nguyen", "1968-01-09", "private", "(416) 555-3044", "linda.nguyen@demo.com", province="ON")
    ahmed = await _make_patient(db, authlib, "Ahmed", "Khan", "1979-05-30", "ohip", "(416) 555-3055", "ahmed.khan@demo.com", hcn="4567-890-123-GH", province="ON")

    # pending verification patients
    await _make_patient(db, authlib, "Sofia", "Martinez", "1995-09-18", "tourist", "(416) 555-3066", "sofia.martinez@demo.com", country="Mexico", verified=False, extra="Visiting family in Toronto")
    await _make_patient(db, authlib, "Robert", "Chen", "1988-12-01", "private", "(416) 555-3077", "robert.chen@demo.com", province="ON", verified=False)

    def pname(last, first):
        return f"{last}, {first}"

    # 5. Prescriptions — 3 active (counter = 3)
    rx_data = [
        (maria, pname("Lopez", "Maria"), "Ramipril", "10 mg", 3, "pharmacy", pharmacies[0]["id"], "received"),
        (john, pname("Smith", "John"), "Metformin", "500 mg", 1, "pickup", None, "under_review"),
        (carlos, pname("Perez", "Carlos"), "Atorvastatin", "20 mg", 3, "pharmacy", pharmacies[1]["id"], "received"),
        (ahmed, pname("Khan", "Ahmed"), "Amlodipine", "5 mg", 2, "pickup", None, "completed"),
    ]
    for pid, nm, med, strength, months, delivery, pharm, status in rx_data:
        ref = await next_ref("RX")
        await db.prescription_requests.insert_one({
            "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": pid, "patient_name": nm,
            "medication_name": med, "strength": strength, "directions": "As previously directed",
            "requested_months": months, "delivery_method": delivery, "pharmacy_id": pharm,
            "new_pharmacy_details": None, "patient_note": "", "internal_status": status,
            "assigned_to": None, "internal_notes": [], "completed_at": now_iso() if status == "completed" else None,
            "created_at": now_iso(), "updated_at": now_iso(),
        })

    # 6. Appointments — 5 requested (counter = 5), with valid slot-based options
    _avail = await db.settings.find_one({"id": "availability"}, {"_id": 0}) or avail_mod.DEFAULT_AVAILABILITY
    _slots = avail_mod.generate_slots(_avail, days=21)
    appt_data = [
        (maria, pname("Lopez", "Maria"), "Follow-up on blood pressure"),
        (john, pname("Smith", "John"), "Persistent cough"),
        (carlos, pname("Perez", "Carlos"), "Annual physical"),
        (linda, pname("Nguyen", "Linda"), "Medication review"),
        (ahmed, pname("Khan", "Ahmed"), "Referral discussion"),
    ]
    for n, (pid, nm, reason) in enumerate(appt_data):
        ref = await next_ref("APT")
        opts = _slots[n * 3: n * 3 + 3] if _slots else []
        if not opts:
            opts = [{"date": "2026-06-22", "time": "11:30", "label": "11:30 AM", "display": "Mon, Jun 22 · 11:30 AM"}]
        await db.appointment_requests.insert_one({
            "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": pid, "patient_name": nm,
            "reason": reason, "patient_note": "",
            "preferred_options": opts,
            "preferred_date": opts[0]["date"], "preferred_time": opts[0]["label"],
            "status": "requested", "staff_note": None,
            "offered_slots": [], "selected_slot": None,
            "confirmed_date": None, "confirmed_time": None, "confirmed_display": None,
            "approved_by": None, "approved_at": None,
            "assigned_to": None, "internal_notes": [],
            "history": [{"status": "requested", "at": now_iso(), "by": "patient"}],
            "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
        })

    # 7. Imaging — 1 active (counter = 1)
    ref = await next_ref("IMG")
    await db.imaging_requests.insert_one({
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": john, "patient_name": pname("Smith", "John"),
        "imaging_type": "xray", "body_part": "Left knee", "reason": "Ongoing pain after fall",
        "patient_note": "Worse when climbing stairs", "internal_status": "new", "assigned_to": None,
        "internal_notes": [], "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    })

    # 8. Patient messages — 4 active (counter = 4)
    msg_data = [
        (maria, pname("Lopez", "Maria"), "Other", "Insurance form", "Could you complete the attached insurance form?"),
        (john, pname("Smith", "John"), "Other", "Address change", "I have moved. Please update my address on file."),
        (carlos, pname("Perez", "Carlos"), "Other", "Sick note", "I need a note for work for last week."),
        (linda, pname("Nguyen", "Linda"), "Other", "Question", "Do I need to fast before my next appointment?"),
    ]
    for pid, nm, cat, subj, bodytext in msg_data:
        ref = await next_ref("MSG")
        await db.patient_messages.insert_one({
            "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": pid, "patient_name": nm,
            "category": cat, "subject": subj, "body": bodytext, "sender": "patient", "status": "new",
            "assigned_to": None, "thread": [{"from": "patient", "body": bodytext, "at": now_iso()}],
            "internal_notes": [], "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
        })

    # 9. Doctor tasks — 2 for staff (counter = 2)
    task_data = [
        (maria, pname("Lopez", "Maria"), "Please call patient regarding CT results."),
        (carlos, pname("Perez", "Carlos"), "Please book follow-up appointment in 2 weeks."),
    ]
    for pid, nm, message in task_data:
        ref = await next_ref("TSK")
        await db.internal_messages.insert_one({
            "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": pid, "patient_name": nm,
            "sender_user_id": None, "sender_name": "Dr. Pablo Aguayo", "sender_role": "physician",
            "recipient_role": "staff", "direction": "task_for_staff", "message": message, "status": "new",
            "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None, "completed_by": None,
        })

    # 10. Referrals ready-to-fax — 2 (counter = 2), with real demo PDFs
    referral_data = [
        (john, "Smith, John", "Cardiology", "Dr. Emily Watson", "Toronto Cardiac Centre", "(416) 555-9001"),
        (maria, "Lopez, Maria", "Dermatology", "Dr. Raj Patel", "Downtown Dermatology", "(416) 555-9002"),
    ]
    for pid, nm, specialty, specialist, clinic, fax in referral_data:
        ref = await next_ref("REF")
        rid = str(uuid.uuid4())
        path = f"{storage.APP_NAME}/referrals/{uuid.uuid4()}.pdf"
        pdf = make_pdf([
            "VISITA - Referral (Demo)", "", f"Patient: {nm}", f"Specialty: {specialty}",
            f"Specialist: {specialist}", f"Clinic: {clinic}", f"Fax: {fax}",
            "", "Generated by the existing VISITA EMR (demo document).",
        ])
        try:
            result = storage.put_object(path, pdf, "application/pdf")
            path = result["path"]
        except Exception:
            pass
        await db.referrals.insert_one({
            "id": rid, "ref_number": ref, "patient_id": pid, "patient_name": nm, "specialty": specialty,
            "specialist_name": specialist, "clinic_name": clinic, "fax_number": fax,
            "referral_date": now_iso()[:10], "storage_path": path, "original_filename": f"Referral_{nm.replace(', ', '_')}.pdf",
            "ready_to_fax": True, "faxed": False, "faxed_at": None, "faxed_by": None,
            "uploaded_by": "Dr. Pablo Aguayo", "uploaded_by_id": None,
            "created_at": now_iso(), "updated_at": now_iso(), "is_deleted": False,
        })

    # 11. Patient-facing referral status records (separate from ready-to-fax queue)
    await db.patient_referrals.insert_many([
        {"id": str(uuid.uuid4()), "patient_id": maria, "specialty": "Dermatology",
         "patient_visible_status": "Awaiting Specialist Response", "created_at": now_iso(), "updated_at": now_iso()},
        {"id": str(uuid.uuid4()), "patient_id": john, "specialty": "Cardiology",
         "patient_visible_status": "Referral Sent to Specialist", "created_at": now_iso(), "updated_at": now_iso()},
        {"id": str(uuid.uuid4()), "patient_id": carlos, "specialty": "Orthopedics",
         "patient_visible_status": "Under Review", "created_at": now_iso(), "updated_at": now_iso()},
    ])

    await db.app_meta.insert_one({"id": "seeded_v1", "at": now_iso()})
