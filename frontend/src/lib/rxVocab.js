// Controlled vocabularies for the Send Prescription smart editor.
// These are neutral terminology lists for DATA ENTRY assistance only — never
// clinical recommendations. Every field remains free-text / typeable.

export const FORM_OPTIONS = [
    // Tablets
    "tablet", "caplet", "chewable tablet", "dispersible tablet",
    "orally disintegrating tablet", "sublingual tablet", "buccal tablet", "effervescent tablet",
    // Capsules
    "capsule", "hard capsule", "softgel",
    // Oral liquids
    "solution", "suspension", "syrup", "oral drops", "elixir", "emulsion",
    // Powders / granules
    "powder", "powder for reconstitution", "granules", "sachet",
    // Oral special
    "lozenge", "troche", "wafer", "oral film",
    // Topical
    "cream", "ointment", "gel", "lotion", "paste", "foam", "shampoo", "topical spray",
    // Transdermal
    "patch",
    // Inhalation
    "metered-dose inhaler", "dry-powder inhaler", "inhalation solution", "nebulizer solution", "inhalation powder",
    // Nasal
    "nasal spray", "nasal drops", "nasal gel",
    // Ophthalmic
    "eye drops", "ophthalmic solution", "ophthalmic suspension", "ophthalmic ointment", "ophthalmic gel",
    // Otic
    "ear drops", "otic solution", "otic suspension",
    // Rectal
    "suppository", "enema", "rectal cream", "rectal ointment", "rectal foam",
    // Vaginal
    "vaginal tablet", "vaginal capsule", "vaginal cream", "vaginal gel", "vaginal suppository", "vaginal ring",
    // Injectable
    "injection solution", "injection suspension", "prefilled syringe", "prefilled pen",
    "vial", "ampoule", "cartridge", "powder for injection",
    // Other
    "implant", "intrauterine system", "irrigation solution", "mouthwash", "dental preparation", "other",
];

export const ATTRIBUTE_OPTIONS = [
    "immediate release", "extended release", "sustained release", "controlled release",
    "modified release", "delayed release", "enteric-coated", "film-coated", "coated",
    "uncoated", "scored", "unscored", "chewable", "dispersible", "soluble",
    "preservative-free", "single-use", "multidose",
];

export const ROUTE_OPTIONS = [
    "Oral / PO", "Sublingual / SL", "Buccal", "Topical", "Transdermal", "Inhalation",
    "Intranasal", "Ophthalmic", "Otic", "Rectal", "Vaginal", "Subcutaneous / SC",
    "Intramuscular / IM", "Intravenous / IV", "Intradermal", "Intra-articular",
    "Intrathecal", "Intravesical", "PEG / feeding tube", "NG tube", "Other",
];

export const FREQUENCY_OPTIONS = [
    "OD / once daily", "BID / twice daily", "TID / three times daily", "QID / four times daily",
    "q4h", "q6h", "q8h", "q12h", "qAM", "HS / qHS", "once weekly", "twice weekly",
    "three times weekly", "monthly", "PRN / as needed", "STAT",
];

export const TIMING_OPTIONS = [
    "AM", "PM", "HS", "AC", "PC", "AC breakfast", "AC lunch", "AC dinner",
    "with food", "on empty stomach",
];

export const DOSE_AMOUNTS = ["¼", "½", "1", "1½", "2", "3"];

export const STRENGTH_UNITS = ["mg", "µg", "g", "units", "mg/mL", "µg/mL", "units/mL", "mg/g", "%", "mEq", "mmol"];

export const DURATION_UNITS = ["day(s)", "week(s)", "month(s)", "dose(s)", "until finished"];

export const REFILL_OPTIONS = ["0", "1", "2", "3", "4", "5", "6"];

export const ACTION_OPTIONS = ["START", "CONTINUE", "HOLD", "STOP", "CHANGE", "RESTART"];

export const EYE_SIDES = ["Right / OD", "Left / OS", "Both / OU"];
export const EAR_SIDES = ["Right", "Left", "Both"];

const norm = (s) => (s || "").toLowerCase();

export function isOphthalmic(form) { return /ophthalmic|eye drop/.test(norm(form)); }
export function isOtic(form) { return /otic|ear drop/.test(norm(form)); }
export function isInjectable(form) { return /inject|syringe|pen|vial|ampoule|cartridge/.test(norm(form)); }
export function isPatch(form) { return /patch/.test(norm(form)); }
export function isInhaler(form) { return /inhal|mdi|dpi|nebuliz/.test(norm(form)); }
export function isTopical(form) { return /cream|ointment|gel|lotion|paste|foam|shampoo|topical/.test(norm(form)); }
export function isLiquid(form) { return /solution|suspension|syrup|elixir|emulsion|drops/.test(norm(form)); }

export function suggestRoute(form) {
    const f = norm(form);
    if (!f) return "";
    if (isOphthalmic(f)) return "Ophthalmic";
    if (isOtic(f)) return "Otic";
    if (isInhaler(f)) return "Inhalation";
    if (isPatch(f)) return "Transdermal";
    if (/nasal/.test(f)) return "Intranasal";
    if (/suppository|enema|rectal/.test(f)) return "Rectal";
    if (/vaginal/.test(f)) return "Vaginal";
    if (/sublingual/.test(f)) return "Sublingual / SL";
    if (/buccal/.test(f)) return "Buccal";
    if (isInjectable(f)) return "Subcutaneous / SC";
    if (isTopical(f)) return "Topical";
    if (/tablet|capsule|caplet|softgel|solution|suspension|syrup|granule|sachet|lozenge|troche|wafer|powder|elixir|drops/.test(f)) return "Oral / PO";
    return "";
}

export function doseUnitsForForm(form) {
    const f = norm(form);
    if (/tablet|caplet|wafer|troche/.test(f)) return ["tablet(s)"];
    if (/capsule|softgel/.test(f)) return ["capsule(s)"];
    if (isInhaler(f)) return ["puff(s)", "inhalation(s)"];
    if (/drop/.test(f)) return ["drop(s)"];
    if (isInjectable(f)) return ["mL", "mg", "µg", "unit(s)"];
    if (isLiquid(f)) return ["mL", "teaspoon"];
    if (isPatch(f)) return ["patch(es)"];
    if (isTopical(f)) return ["application", "thin layer"];
    if (/suppository/.test(f)) return ["suppository"];
    if (/spray/.test(f)) return ["spray(s)"];
    if (/lozenge/.test(f)) return ["lozenge"];
    if (/sachet|granule|powder/.test(f)) return ["sachet"];
    return ["tablet(s)", "capsule(s)", "mL", "unit(s)"];
}

export function quantityUnitsForForm(form) {
    const f = norm(form);
    const base = ["tablet", "capsule", "mL", "bottle", "tube", "inhaler", "device", "pen",
        "syringe", "vial", "ampoule", "patch", "suppository", "sachet", "gram", "unit"];
    if (/tablet/.test(f)) return ["tablet", ...base.filter((x) => x !== "tablet")];
    if (/capsule|softgel/.test(f)) return ["capsule", ...base.filter((x) => x !== "capsule")];
    if (isInhaler(f)) return ["inhaler", "device", ...base];
    if (isInjectable(f)) return ["pen", "syringe", "vial", "ampoule", "mL", ...base];
    if (isPatch(f)) return ["patch", ...base];
    if (isLiquid(f)) return ["mL", "bottle", ...base];
    if (isTopical(f)) return ["tube", "gram", ...base];
    return base;
}
