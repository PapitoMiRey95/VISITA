"""Longitudinal METRICS summary (Phase 2A3.4). Vital metrics from canonical visit vitals; lab metrics PENDING
(no structured numeric lab source exists in VIen yet — exam_results is document-based). Arithmetic means only."""
from datetime import datetime, timedelta, timezone

VITAL_METRICS = [("Sst", "systolic_bp", "Systolic BP"), ("Dst", "diastolic_bp", "Diastolic BP"), ("Bpm", "heart_rate", "Heart rate"),
                 ("Kg", "weight_kg", "Weight (kg)"), ("Lbs", "weight_lb", "Weight (lb) = kg × 2.20462")]
LAB_METRICS = [("Hg", "Hemoglobin"), ("WBC", "White blood cells"), ("PLT", "Platelets"), ("eGFR", "Estimated GFR"), ("FBS", "Fasting blood sugar"),
               ("HgA1C", "Hemoglobin A1c"), ("eAG", "Estimated average glucose (formula pending — not in supplied source)"), ("LDL", "LDL cholesterol"),
               ("T/HDL", "Total / HDL cholesterol ratio"), ("TSH", "Thyroid stimulating hormone"), ("PSA", "Prostate specific antigen")]


def _mean(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 2) if vals else None


def daily_observations(visits: list) -> list:
    """Access tblDim intent: ONE dimensions snapshot per calendar day = LAST successfully persisted vitals that day."""
    by_day = {}
    for v in visits:
        vit = v.get("vitals") or {}
        obs_at = vit.get("updated_at") or v.get("started_at")
        if not obs_at:
            continue
        day = obs_at[:10]
        if day not in by_day or obs_at > by_day[day]["observed_at"]:
            row = {k: vit.get(k) for _, k, _ in VITAL_METRICS if k != "weight_lb"}
            row["weight_lb"] = round(row["weight_kg"] * 2.20462, 2) if isinstance(row.get("weight_kg"), (int, float)) else None
            by_day[day] = {"day": day, "observed_at": obs_at, "visit_id": v.get("id"), **row}
    return sorted(by_day.values(), key=lambda r: r["observed_at"])


def summarize(visits: list, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    obs = daily_observations(visits)
    m3, m12 = (now - timedelta(days=91)).isoformat(), (now - timedelta(days=365)).isoformat()
    rows = []
    for label, key, tip in VITAL_METRICS:
        valid = [o for o in obs if isinstance(o.get(key), (int, float))]
        recent = valid[-1] if valid else None
        rows.append({"label": label, "key": key, "tooltip": tip, "source": "visits.vitals", "status": "CONNECTED",
                     "recent": recent[key] if recent else None, "recent_at": recent["observed_at"] if recent else None,
                     "avg_3mo": _mean([o[key] for o in valid if o["observed_at"] >= m3]),
                     "avg_12mo": _mean([o[key] for o in valid if o["observed_at"] >= m12]),
                     "avg_global": _mean([o[key] for o in valid]), "n": len(valid)})
    for label, tip in LAB_METRICS:
        rows.append({"label": label, "key": label, "tooltip": tip, "source": None, "status": "PENDING",
                     "recent": None, "recent_at": None, "avg_3mo": None, "avg_12mo": None, "avg_global": None, "n": 0})
    return {"columns": ["RECENT", "3 MO AVG", "12 MO AVG", "GLOBAL AVG"], "rows": rows, "observation_days": len(obs),
            "window_3mo_from": m3[:10], "window_12mo_from": m12[:10]}
