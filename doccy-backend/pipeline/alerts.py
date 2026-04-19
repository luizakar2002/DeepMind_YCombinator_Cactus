import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).parent.parent / "data" / "red_flag_rules.json"
_rules_cache: dict | None = None


def _load_rules() -> dict:
    global _rules_cache
    if _rules_cache is None:
        _rules_cache = json.loads(_RULES_PATH.read_text())
        logger.info(f"Loaded alert rules from {_RULES_PATH}")
    return _rules_cache


def _norm(text: str) -> str:
    return text.lower()


def _symptom_texts(session_entities: dict) -> list[str]:
    texts = []
    for s in session_entities.get("symptoms", []):
        if isinstance(s, dict):
            texts.append(_norm(s.get("text", "")))
        else:
            texts.append(_norm(str(s)))
    return texts


def _drugs_norm(session_entities: dict) -> set[str]:
    return {_norm(d) for d in session_entities.get("drugs_mentioned", [])}


def _flagged_lab_ids(patient) -> set[str]:
    """Build set of 'TestName_FLAG' strings for requires_flag matching."""
    if not patient:
        return set()
    return {f"{l.test}_{l.flag}" for l in patient.lab_results if l.flag}


def check_alerts(
    session_entities: dict,
    patient,
    already_flagged: set,
) -> list[dict]:
    """
    Evaluate all rules in red_flag_rules.json against current session entities.
    Returns alert dicts ready to emit. Mutates already_flagged to prevent repeats.
    """
    rules = _load_rules()
    alerts = []
    symptoms = _symptom_texts(session_entities)
    drugs = _drugs_norm(session_entities)
    lab_flags = _flagged_lab_ids(patient)

    # ── 1. Single red-flag symptoms ──────────────────────────────────────────
    for rule in rules.get("red_flag_symptoms", []):
        rid = rule["id"]
        if rid in already_flagged:
            continue
        pattern = _norm(rule["pattern"])
        if any(pattern in s for s in symptoms):
            alerts.append({
                "level": rule["level"],
                "type": "red_flag",
                "rule_id": rid,
                "message": rule["message"],
            })
            already_flagged.add(rid)

    # ── 2. Symptom combinations ──────────────────────────────────────────────
    for rule in rules.get("symptom_combinations", []):
        rid = rule["id"]
        if rid in already_flagged:
            continue
        patterns = [_norm(p) for p in rule["patterns"]]
        if all(any(p in s for s in symptoms) for p in patterns):
            alerts.append({
                "level": rule["level"],
                "type": "symptom_combination",
                "rule_id": rid,
                "message": rule["message"],
            })
            already_flagged.add(rid)

    # ── 3. Drug interactions ─────────────────────────────────────────────────
    for rule in rules.get("drug_interactions", []):
        rid = rule["id"]
        if rid in already_flagged:
            continue

        # Check required lab flag if specified
        req_flag = rule.get("requires_flag")
        if req_flag and req_flag not in lab_flags:
            continue

        # Named drug pair interaction
        if "drugs" in rule:
            rule_drugs = [_norm(d) for d in rule["drugs"]]
            if all(any(rd in d or d in rd for d in drugs) for rd in rule_drugs):
                alerts.append({
                    "level": rule["level"],
                    "type": "drug_interaction",
                    "rule_id": rid,
                    "message": rule["message"],
                })
                already_flagged.add(rid)

        # Drug class check (any one of these drugs triggers the rule)
        elif "drug_classes" in rule:
            drug_classes = [_norm(d) for d in rule["drug_classes"]]
            if any(any(dc in d or d in dc for d in drugs) for dc in drug_classes):
                alerts.append({
                    "level": rule["level"],
                    "type": "drug_interaction",
                    "rule_id": rid,
                    "message": rule["message"],
                })
                already_flagged.add(rid)

    return alerts
