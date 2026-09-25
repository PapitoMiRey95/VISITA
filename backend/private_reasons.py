"""Code-based Reason-for-Visit taxonomy for the Private/Uninsured workflow.

Stable internal codes are separate from display labels. Never store the taxonomy
as editable DB content (per product decision). `validate_path` confirms a leaf
selection and returns the human breadcrumb + leaf label.
"""

# Each node: code -> {"label": str, "children": {code: node} | None}
REASON_TAXONOMY = {
    "new_concern": {"label": "New Medical Concern"},
    "followup": {"label": "Follow-up / Existing Condition"},
    "medication": {"label": "Medication / Prescription Refill"},
    "vaccines": {"label": "Vaccines / Injections"},
    "preventive": {"label": "Preventive / Routine Care"},
    "test_results": {"label": "Test / Results"},
    "referral": {"label": "Referral / Specialist"},
    "forms": {
        "label": "Forms / Medical Documentation",
        "children": {
            "employment_school": {
                "label": "Employment / School",
                "children": {
                    "sick_note": {"label": "Sick note / Medical note"},
                    "return_to_work": {"label": "Return-to-work note"},
                    "work_restrictions": {"label": "Work restrictions / accommodations"},
                    "school_form": {"label": "School / University form"},
                    "camp_daycare": {"label": "Camp / Daycare form"},
                    "fitness_sports": {"label": "Fitness / Sports form"},
                    "other": {"label": "Other"},
                },
            },
            "disability_benefits": {
                "label": "Disability / Benefits",
                "children": {
                    "odsp": {"label": "ODSP"},
                    "dtc_t2201": {"label": "Disability Tax Credit / T2201"},
                    "cpp_disability": {"label": "CPP Disability"},
                    "private_disability": {"label": "Private disability insurance"},
                    "functional_abilities": {"label": "Functional abilities / limitations"},
                    "other": {"label": "Other"},
                },
            },
            "driving_transport": {
                "label": "Driving / Transportation",
                "children": {
                    "driver_medical": {"label": "Driver medical form"},
                    "medical_condition_report": {"label": "Medical Condition Report"},
                    "accessible_parking": {"label": "Accessible Parking Permit"},
                    "other": {"label": "Other"},
                },
            },
            "workplace_wsib": {
                "label": "Workplace / WSIB",
                "children": {
                    "wsib_form_8": {"label": "WSIB Form 8"},
                    "functional_abilities_form": {"label": "Functional Abilities Form"},
                    "wsib_progress": {"label": "WSIB progress documentation"},
                    "occupational_mental_stress": {"label": "Occupational mental stress documentation"},
                    "other": {"label": "Other WSIB form"},
                },
            },
            "insurance": {
                "label": "Insurance",
                "children": {
                    "life_insurance": {"label": "Life insurance"},
                    "travel_insurance": {"label": "Travel insurance"},
                    "disability_insurance": {"label": "Disability insurance"},
                    "attending_physician_statement": {"label": "Attending Physician Statement"},
                    "other": {"label": "Other insurance documentation"},
                },
            },
            "government_tax": {
                "label": "Government / Tax",
                "children": {
                    "dtc": {"label": "Disability Tax Credit"},
                    "odsp": {"label": "ODSP"},
                    "other": {"label": "Other government / benefit form"},
                },
            },
            "other_documentation": {
                "label": "Other Documentation",
                "children": {
                    "medical_certificate": {"label": "Medical certificate"},
                    "patient_letter": {"label": "Patient-requested letter"},
                    "medical_summary": {"label": "Medical information / summary"},
                    "other": {"label": "Other"},
                },
            },
        },
    },
    "womens_health": {"label": "Women's / Reproductive Health"},
    "mental_health": {"label": "Mental Health"},
    "minor_procedure": {"label": "Minor Procedure / Office Treatment"},
    "other": {"label": "Other"},
}


def validate_path(codes):
    """Validate a list of codes from root to leaf. Returns (labels_list) or None.

    A valid selection ends on a node with no children (leaf)."""
    if not codes or not isinstance(codes, list):
        return None
    node_map = REASON_TAXONOMY
    labels = []
    node = None
    for code in codes:
        node = node_map.get(code)
        if not node:
            return None
        labels.append(node["label"])
        node_map = node.get("children") or {}
    # Must end on a leaf (no remaining children)
    if node is not None and node.get("children"):
        return None
    return labels
