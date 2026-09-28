"""Regression tests for the multi-medication Access parser (rx_parser).

Guards against the reported failure where multiple medications collapsed into
the first medication's SIG. Pure-unit (no server / DB needed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rx_parser  # noqa: E402

MULTI_PARAGRAPH = (
    "Early vacation supply dispense "
    "Acetaminophen 325 mg OD-BID PRN #90 ninety dispense #90 at once no refills. "
    "Hold Amlodipine besylate 10 mg tablet: 1 tablet HS "
    "Bisoprolol fumarate 05 mg tablet: 1 tablet HS "
    "Candesartan cilexetil/Hydrochlorothiazide 16 mg/12.5 mg tablet: 1 tablet HS "
    "Clopidogrel 075 mg tablet film-coated unscored: 1 tablet HS "
    "Ezetimibe 10 mg OD, LU 380 "
    "Gliclazide 60 mg tablet modified release scored: 1 tablet AC breakfast, "
    "\u00bd tablet AC dinner "
    "Metformin/Sitagliptin (Janumet) 1000 mg/50 mg tablet immediate film-coated: "
    "1 tablet AC breakfast, 1 tablet AC dinner "
    "Rosuvastatin calcium 20 mg tablet: 1 tablet OD "
    "Start Felodipine 05 mg tablet extended release coated scored: 1 tablet HS "
    "Number of months: 3 Number of refills: 0"
)

MULTI_NEWLINE = MULTI_PARAGRAPH.replace(". ", ".\n").replace(" Hold", "\nHold")


def _by_drug(meds, needle):
    for m in meds:
        if m["drug"] and needle.lower() in m["drug"].lower():
            return m
    raise AssertionError(f"medication containing {needle!r} not found")


def test_ten_separate_medications():
    r = rx_parser.parse_access_rx(MULTI_PARAGRAPH)
    meds = r["medications"]
    assert len(meds) == 10, [m["drug"] for m in meds]


def test_bisoprolol_not_inside_acetaminophen_sig():
    r = rx_parser.parse_access_rx(MULTI_PARAGRAPH)
    acet = _by_drug(r["medications"], "Acetaminophen")
    assert "bisoprolol" not in (acet.get("sig") or "").lower()
    assert "candesartan" not in (acet.get("sig") or "").lower()
    assert acet["sig"] == "OD-BID PRN"
    assert acet["quantity"] == "90"
    assert acet["refills"] == "0"
    assert "dispense" in (acet["additional_instructions"] or "").lower()


def test_every_medication_has_original_text():
    r = rx_parser.parse_access_rx(MULTI_PARAGRAPH)
    for m in r["medications"]:
        assert m["original_text"] and m["drug"] and m["drug"] in m["original_text"]


def test_hold_and_start_preserved():
    r = rx_parser.parse_access_rx(MULTI_PARAGRAPH)
    assert _by_drug(r["medications"], "Amlodipine")["action"] == "HOLD"
    assert _by_drug(r["medications"], "Felodipine")["action"] == "START"


def test_gliclazide_sig_isolated():
    m = _by_drug(rx_parser.parse_access_rx(MULTI_PARAGRAPH)["medications"], "Gliclazide")
    assert m["sig"] == "1 tablet AC breakfast, \u00bd tablet AC dinner"
    assert "metformin" not in (m["sig"] or "").lower()


def test_janumet_sig_isolated():
    m = _by_drug(rx_parser.parse_access_rx(MULTI_PARAGRAPH)["medications"], "Janumet")
    assert m["sig"] == "1 tablet AC breakfast, 1 tablet AC dinner"
    assert "rosuvastatin" not in (m["sig"] or "").lower()
    assert m["strength"] == "1000 mg/50 mg"


def test_candesartan_combo():
    m = _by_drug(rx_parser.parse_access_rx(MULTI_PARAGRAPH)["medications"], "Candesartan")
    assert m["strength"] == "16 mg/12.5 mg"
    assert m["sig"] == "1 tablet HS"


def test_ezetimibe_lu_code():
    m = _by_drug(rx_parser.parse_access_rx(MULTI_PARAGRAPH)["medications"], "Ezetimibe")
    assert m["sig"] == "OD"
    assert "LU 380" in (m["additional_instructions"] or "")


def test_months_refills_prescription_level():
    r = rx_parser.parse_access_rx(MULTI_PARAGRAPH)
    assert r["months"] == 3
    assert r["refills"] == 0
    # not attached to every medication
    for m in r["medications"]:
        assert m.get("refills") in (None, "0") or m["drug"].lower().startswith("acet")


def test_note_is_prescription_level():
    r = rx_parser.parse_access_rx(MULTI_PARAGRAPH)
    assert "vacation supply" in (r["note"] or "").lower()


def test_newline_input_also_ten():
    r = rx_parser.parse_access_rx(MULTI_NEWLINE)
    assert len(r["medications"]) == 10, [m["drug"] for m in r["medications"]]


def test_single_medication_still_works():
    txt = "Candesartan cilexetil 16 mg tablet film-coated scored: 1 tablet HS\nNumber of months: 3\nNumber of refills: 0"
    r = rx_parser.parse_access_rx(txt)
    assert len(r["medications"]) == 1
    m = r["medications"][0]
    assert m["drug"] == "Candesartan cilexetil"
    assert m["strength"] == "16 mg"
    assert m["sig"] == "1 tablet HS"
    assert r["months"] == 3 and r["refills"] == 0


def test_empty_and_garbage_input():
    assert rx_parser.parse_access_rx("")["medications"] == []
    r = rx_parser.parse_access_rx("please call the office tomorrow")
    assert r["medications"] == []
    assert r["note"]
