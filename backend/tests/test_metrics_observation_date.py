from datetime import datetime, timezone
from metrics import daily_observations, summarize, eag_from_hga1c

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


def _v(vid, started, updated, sst):
    return {"id": vid, "started_at": started, "vitals": {"systolic_bp": sst, "updated_at": updated}}


def test_eag_formula_matches_access():
    assert eag_from_hga1c(6.0) == 6.97
    assert eag_from_hga1c(None) is None


def test_old_visit_edited_today_stays_in_original_period():
    visits = [
        _v("old", "2026-01-10T10:00:00+00:00", "2026-06-15T09:00:00+00:00", 150),  # Jan visit edited today
        _v("new", "2026-05-20T10:00:00+00:00", "2026-05-20T10:05:00+00:00", 120),
    ]
    obs = daily_observations(visits)
    assert [o["day"] for o in obs] == ["2026-01-10", "2026-05-20"]
    row = next(r for r in summarize(visits, NOW)["rows"] if r["key"] == "systolic_bp")
    assert row["recent"] == 120 and row["recent_at"].startswith("2026-05-20")  # RECENT = latest clinical date
    assert row["avg_3mo"] == 120  # Jan visit NOT pulled into 3-month window by today's edit
    assert row["avg_12mo"] == 135 and row["avg_global"] == 135


def test_same_day_tiebreak_uses_updated_at():
    visits = [
        _v("a", "2026-03-01T08:00:00+00:00", "2026-03-01T08:10:00+00:00", 100),
        _v("b", "2026-03-01T09:00:00+00:00", "2026-03-01T08:05:00+00:00", 130),
    ]
    obs = daily_observations(visits)
    assert len(obs) == 1 and obs[0]["systolic_bp"] == 100 and obs[0]["visit_id"] == "a"
