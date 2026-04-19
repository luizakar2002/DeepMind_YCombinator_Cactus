import json
import re
from pathlib import Path
from models.patient import Patient

PATIENTS_DIR = Path(__file__).parent.parent / "data" / "patients"

# Symptom text → lab test name: if a symptom matches and that lab is flagged, surface it
_SYMPTOM_LAB_MAP = {
    "fatigue":          ["Hemoglobin", "TSH", "HbA1c"],
    "tired":            ["Hemoglobin", "TSH"],
    "weight gain":      ["TSH"],
    "weight loss":      ["HbA1c"],
    "shortness of breath": ["BNP", "Hemoglobin"],
    "breathless":       ["BNP", "Hemoglobin"],
    "chest":            ["BNP"],
    "swelling":         ["BNP", "eGFR"],
    "palpitation":      ["TSH"],
    "cold":             ["TSH"],
    "blurry vision":    ["HbA1c"],
    "polyuria":         ["HbA1c"],
    "thirst":           ["HbA1c"],
}


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def load_all_patients() -> list[Patient]:
    patients = []
    for path in PATIENTS_DIR.glob("*.json"):
        with open(path) as f:
            patients.append(Patient(**json.load(f)))
    return patients


def load_patient(patient_id: str) -> Patient | None:
    path = PATIENTS_DIR / f"{patient_id}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return Patient(**json.load(f))


# Hardcoded drug-drug interaction table.
# Keys are frozensets of normalised drug name fragments so partial matches work.
# Each value: (level, message)
_INTERACTION_TABLE: dict[frozenset, tuple[str, str]] = {
    frozenset(["aspirin", "ibuprofen"]): (
        "warning",
        "Ibuprofen antagonises Aspirin's irreversible antiplatelet effect and raises GI bleed risk when combined.",
    ),
    frozenset(["aspirin", "naproxen"]): (
        "warning",
        "Naproxen may competitively inhibit Aspirin's antiplatelet binding — take Aspirin ≥2h before naproxen.",
    ),
    frozenset(["aspirin", "warfarin"]): (
        "critical",
        "Aspirin + Warfarin significantly elevates haemorrhage risk — dual therapy requires explicit clinical justification.",
    ),
    frozenset(["aspirin", "clopidogrel"]): (
        "warning",
        "Dual antiplatelet therapy (Aspirin + Clopidogrel) — verify this is intentional; bleeding risk is elevated.",
    ),
    frozenset(["lisinopril", "ibuprofen"]): (
        "warning",
        "NSAIDs blunt ACE inhibitor efficacy and can precipitate acute kidney injury — avoid if eGFR already reduced.",
    ),
    frozenset(["lisinopril", "naproxen"]): (
        "warning",
        "Naproxen reduces Lisinopril's antihypertensive effect and stresses renal perfusion.",
    ),
    frozenset(["lisinopril", "potassium"]): (
        "warning",
        "ACE inhibitors retain potassium — concurrent potassium supplementation risks hyperkalaemia.",
    ),
    frozenset(["lisinopril", "spironolactone"]): (
        "warning",
        "ACE inhibitor + Spironolactone: significant hyperkalaemia risk — monitor K⁺ closely.",
    ),
    frozenset(["metformin", "alcohol"]): (
        "warning",
        "Alcohol potentiates Metformin-associated lactic acidosis risk — advise abstinence or strict moderation.",
    ),
    frozenset(["metformin", "ibuprofen"]): (
        "warning",
        "NSAIDs reduce renal clearance of Metformin — increases lactic acidosis risk, especially with eGFR 58.",
    ),
    frozenset(["metformin", "contrast"]): (
        "critical",
        "Hold Metformin ≥48h before and after iodinated contrast — risk of contrast-induced nephropathy and lactic acidosis.",
    ),
    frozenset(["levothyroxine", "calcium"]): (
        "info",
        "Calcium impairs Levothyroxine absorption — separate doses by ≥4 hours.",
    ),
    frozenset(["levothyroxine", "iron"]): (
        "info",
        "Iron reduces Levothyroxine absorption significantly — separate by ≥2 hours.",
    ),
    frozenset(["levothyroxine", "omeprazole"]): (
        "info",
        "PPIs (omeprazole) may reduce Levothyroxine absorption — consider dose adjustment if TSH remains elevated.",
    ),
    frozenset(["levothyroxine", "cholestyramine"]): (
        "warning",
        "Cholestyramine markedly reduces Levothyroxine absorption — separate by ≥4–6 hours.",
    ),
}


def _interaction_key(drug_a: str, drug_b: str) -> frozenset | None:
    """Return the matching table key if these two drugs have a known interaction."""
    norm_a, norm_b = _normalise(drug_a), _normalise(drug_b)
    for key in _INTERACTION_TABLE:
        parts = list(key)
        if len(parts) != 2:
            continue
        a_match = parts[0] in norm_a or norm_a in parts[0]
        b_match = parts[1] in norm_b or norm_b in parts[1]
        ab_match = parts[0] in norm_b or norm_b in parts[0]
        ba_match = parts[1] in norm_a or norm_a in parts[1]
        if (a_match and b_match) or (ab_match and ba_match):
            return key
    return None


def check_drug_entities(
    new_entities: dict,
    patient: Patient,
    already_flagged: set,
) -> list[dict]:
    """
    For each drug entity extracted from the current chunk:
      1. Check against EHR medication list → emit drug_contradiction if absent.
      2. Cross-check against each EHR med via _INTERACTION_TABLE → emit drug_interaction.
    Both event types are returned from a single function.
    """
    events = []
    ehr_meds = patient.medications
    ehr_meds_norm = {_normalise(m.name): m for m in ehr_meds}

    for drug in new_entities.get("drugs_mentioned", []):
        drug_norm = _normalise(drug)

        # ── Check 1: drug vs EHR medication list ────────────────────────────
        in_ehr = any(
            ehr_n in drug_norm or drug_norm in ehr_n
            for ehr_n in ehr_meds_norm
        )
        contra_key = f"drug_contra:{drug_norm}"
        if not in_ehr and contra_key not in already_flagged:
            events.append({
                "level": "warning",
                "type": "drug_contradiction",
                "message": (
                    f"{drug} is not in the patient's EHR medication list. "
                    "Self-medicating, new script, or transcription error?"
                ),
                "detail": {
                    "mentioned_drug": drug,
                    "ehr_medications": [m.name for m in ehr_meds],
                },
            })
            already_flagged.add(contra_key)

        # ── Check 2: drug × each EHR med via interaction table ──────────────
        for ehr_norm, ehr_med in ehr_meds_norm.items():
            if drug_norm == ehr_norm or drug_norm in ehr_norm or ehr_norm in drug_norm:
                continue  # same drug — skip self-interaction
            key = _interaction_key(drug, ehr_med.name)
            if key is None:
                continue
            flag_key = f"drug_ix:{drug_norm}:{ehr_norm}"
            if flag_key in already_flagged:
                continue
            level, message = _INTERACTION_TABLE[key]
            events.append({
                "level": level,
                "type": "drug_interaction",
                "message": message,
                "detail": {
                    "mentioned_drug": drug,
                    "ehr_drug": ehr_med.name,
                    "ehr_dose": ehr_med.dose,
                },
            })
            already_flagged.add(flag_key)

    return events


def check_contradictions(
    new_entities: dict,
    patient: Patient,
    session_entities: dict,
    already_flagged: set,
    chunk_index: int = 0,
) -> list[dict]:
    """
    Cross-reference freshly extracted entities against the patient's EHR.
    Returns a list of contradiction dicts ready to emit as WebSocket events.
    `already_flagged` is a mutable set of keys updated in-place to avoid repeat alerts.
    """
    events = []

    ehr_meds_norm  = {_normalise(m.name) for m in patient.medications}
    ehr_allergy_norm = {_normalise(a.substance): a for a in patient.allergies}
    flagged_labs   = {l.test: l for l in patient.lab_results if l.flag}

    # ── 1. Drug mentioned that is in the patient's allergy list ─────────────
    for drug in new_entities.get("drugs_mentioned", []):
        key = f"allergy:{_normalise(drug)}"
        if key in already_flagged:
            continue
        for allergy_name, allergy in ehr_allergy_norm.items():
            if allergy_name in _normalise(drug) or _normalise(drug) in allergy_name:
                events.append({
                    "level": "critical",
                    "type": "allergy_conflict",
                    "message": f"{drug} mentioned — patient has documented {allergy.reaction} to {allergy.substance}.",
                    "detail": {"drug": drug, "allergy": allergy.model_dump()},
                })
                already_flagged.add(key)
                break

    # ── 2. Drug mentioned not in EHR medication list ─────────────────────────
    for drug in new_entities.get("drugs_mentioned", []):
        key = f"undisclosed:{_normalise(drug)}"
        if key in already_flagged:
            continue
        if not any(ehr_med in _normalise(drug) or _normalise(drug) in ehr_med
                   for ehr_med in ehr_meds_norm):
            events.append({
                "level": "warning",
                "type": "undisclosed_drug",
                "message": f"{drug} mentioned but not in EHR medication list — undisclosed or new prescription?",
                "detail": {"drug": drug, "ehr_medications": [m.name for m in patient.medications]},
            })
            already_flagged.add(key)

    # ── 3. Symptom correlates with a flagged lab result ──────────────────────
    for symptom in new_entities.get("symptoms", []):
        text = symptom.get("text", "") if isinstance(symptom, dict) else str(symptom)
        norm = _normalise(text)
        for keyword, lab_names in _SYMPTOM_LAB_MAP.items():
            if keyword not in norm:
                continue
            for lab_name in lab_names:
                if lab_name not in flagged_labs:
                    continue
                key = f"lab:{lab_name}:{keyword}"
                if key in already_flagged:
                    continue
                lab = flagged_labs[lab_name]
                events.append({
                    "level": "info",
                    "type": "lab_correlation",
                    "message": (
                        f"'{text}' aligns with flagged lab: {lab.test} {lab.value}{lab.unit} "
                        f"[{lab.flag}] from {lab.date}."
                    ),
                    "detail": {"symptom": text, "lab": lab.model_dump()},
                })
                already_flagged.add(key)

    # ── 4. EHR drug not mentioned at all after session has grown ─────────────
    # Wait until chunk 5 so the conversation has some substance first
    session_drugs_norm = {_normalise(d) for d in session_entities.get("drugs_mentioned", [])}
    if session_drugs_norm and chunk_index >= 5:
        for med in patient.medications:
            key = f"unmentioned:{_normalise(med.name)}"
            if key in already_flagged:
                continue
            if not any(_normalise(med.name) in sd or sd in _normalise(med.name)
                       for sd in session_drugs_norm):
                events.append({
                    "level": "info",
                    "type": "ehr_drug_not_mentioned",
                    "message": f"{med.name} {med.dose} is in the EHR but hasn't come up — consider asking about adherence.",
                    "detail": {"medication": med.model_dump()},
                })
                already_flagged.add(key)

    return events
