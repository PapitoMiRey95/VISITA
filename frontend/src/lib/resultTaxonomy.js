// Broad result/report taxonomy with subtype support. Free-text subtype is also
// allowed where needed — this is intentionally NOT an exhaustive list of every
// Ontario test. Used by the internal release dialog and for patient-facing labels.
export const RESULT_TAXONOMY = [
    {
        value: "LABORATORY", label: "Laboratory",
        subtypes: ["Bloodwork", "Urine", "Stool", "Microbiology / Culture", "Serology / Immunology",
            "Coagulation", "Hormonal / Endocrine", "Therapeutic Drug Monitoring", "Other Laboratory"],
    },
    {
        value: "DIAGNOSTIC_IMAGING", label: "Diagnostic Imaging",
        subtypes: ["X-Ray", "Ultrasound", "Mammogram / Breast Imaging", "CT", "MRI",
            "Bone Mineral Density / DEXA", "Other Imaging"],
    },
    {
        value: "CARDIAC_TESTS", label: "Cardiac Tests",
        subtypes: ["ECG", "Holter / Event Monitor", "Ambulatory Blood Pressure Monitoring", "Echocardiogram",
            "Exercise Stress Test", "Stress Echo", "Other Cardiac Test"],
    },
    {
        value: "PULMONARY_SLEEP", label: "Pulmonary / Sleep",
        subtypes: ["Spirometry", "Pulmonary Function Test", "Bronchodilator Testing", "Methacholine Challenge",
            "Exercise / Oxygen Testing", "6-Minute Walk Test", "Sleep Study", "Other Respiratory Test"],
    },
    {
        value: "PATHOLOGY_CYTOLOGY", label: "Pathology / Cytology",
        subtypes: ["Biopsy / Pathology", "Surgical Pathology", "Dermatopathology", "Cervical HPV / Cytology",
            "Other Cytology"],
    },
    {
        value: "SCREENING", label: "Screening",
        subtypes: ["FIT / Colorectal Screening", "Cervical Screening", "Mammography / Breast Screening",
            "Other Screening"],
    },
    {
        value: "OTHER_REPORTS", label: "Other Reports",
        subtypes: ["EEG", "EMG / Nerve Conduction", "Endoscopy / Colonoscopy Report",
            "Specialist Consultation Report", "Procedure Report", "Other Clinical Report"],
    },
];

export const CATEGORY_LABEL = RESULT_TAXONOMY.reduce((m, c) => { m[c.value] = c.label; return m; }, {});
