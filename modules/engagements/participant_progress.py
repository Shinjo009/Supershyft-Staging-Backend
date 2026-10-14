"""Engagement-scoped participant lifecycle progress (admin ops)."""

from __future__ import annotations

from typing import Any

from modules.engagements.enums import EngagementKind
from modules.engagements.metsights_pro_validation import BIO_AI_ENGAGEMENT_TYPE_CODES

_STAGE_DEFS: tuple[tuple[str, str], ...] = (
    ("enrolled", "Enrolled"),
    ("booking_id", "Booking ID"),
    ("questionnaire", "Questionnaire"),
    ("blood_report", "Blood PDF"),
    ("blood_values", "Blood values"),
    ("bio_ai_json", "BioAI JSON"),
    ("bio_ai_report", "BioAI PDF"),
    ("consultation_booked", "Consult booked"),
    ("consultation_done", "Consult done"),
)

_CONSULTATION_TYPE_CODES = frozenset(
    {
        EngagementKind.bio_ai_with_consultation.value,
        EngagementKind.blood_test_with_consultation.value,
        EngagementKind.consultation.value,
    }
)


def stage_keys_for_engagement_type(type_code: str | None) -> list[str]:
    code = (type_code or "").strip().lower()
    keys = ["enrolled", "booking_id", "questionnaire"]
    if code in {
        EngagementKind.blood_test.value,
        EngagementKind.blood_test_with_consultation.value,
        EngagementKind.bio_ai.value,
    } or code in BIO_AI_ENGAGEMENT_TYPE_CODES:
        keys.extend(["blood_report", "blood_values"])
    if code in BIO_AI_ENGAGEMENT_TYPE_CODES:
        keys.extend(["bio_ai_json", "bio_ai_report"])
    if code in _CONSULTATION_TYPE_CODES:
        keys.extend(["consultation_booked", "consultation_done"])
    return keys


def _consultation_type_enabled(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, dict):
        if value.get("enabled") is True:
            return True
        if value.get("want") is True:
            return True
        if value.get("offer") is True:
            return True
    return False


def _offered_consultation_types(engagement_consultations: Any) -> list[str]:
    if not isinstance(engagement_consultations, dict):
        return []
    offered: list[str] = []
    for key, value in engagement_consultations.items():
        if _consultation_type_enabled(value):
            offered.append(str(key))
    return offered


def _participant_wants_consultations(
    participant_consultations: dict[str, Any],
    offered_types: list[str],
) -> list[dict[str, Any]]:
    wants: list[dict[str, Any]] = []
    for expert_type in offered_types:
        pref = participant_consultations.get(expert_type)
        if not isinstance(pref, dict):
            continue
        if pref.get("want") is True:
            wants.append(pref)
    return wants


def consultation_stage_statuses(
    participant_consultations: dict[str, Any],
    offered_types: list[str],
) -> tuple[bool, bool, bool]:
    """Return booked, done, not_applicable for consultation stages."""
    if not offered_types:
        return False, False, True

    wants = _participant_wants_consultations(participant_consultations, offered_types)
    if not wants:
        return False, False, True

    booked = all(
        bool((p.get("date") or "").strip())
        or bool((p.get("slot") or "").strip())
        or bool((p.get("cabin") or "").strip())
        for p in wants
    )
    done = all(
        bool(p.get("done"))
        or bool((p.get("consultation_summary") or "").strip())
        for p in wants
    )
    return booked, done, False


def _consultation_flags(
    participant_consultations: dict[str, Any],
    offered_types: list[str],
) -> tuple[bool, bool]:
    booked, done, not_applicable = consultation_stage_statuses(
        participant_consultations, offered_types
    )
    if not_applicable:
        return False, False
    return booked, done


def _questionnaire_complete(q_state: str) -> bool:
    return (q_state or "").strip().lower() == "filled"


def _stage_complete(stage_key: str, *, participant_row: dict[str, Any], q_state: str) -> bool:
    if stage_key == "enrolled":
        return True
    if stage_key == "booking_id":
        return bool(participant_row.get("has_booking_id"))
    if stage_key == "questionnaire":
        return _questionnaire_complete(q_state)
    if stage_key == "blood_report":
        return bool(participant_row.get("has_blood_report"))
    if stage_key == "blood_values":
        return bool(participant_row.get("has_blood_values"))
    if stage_key == "bio_ai_json":
        return bool(participant_row.get("has_bio_ai_json")) and bool(
            participant_row.get("has_blood_values")
        )
    if stage_key == "bio_ai_report":
        return bool(participant_row.get("has_bio_ai_report"))
    if stage_key == "consultation_booked":
        return bool(participant_row.get("_consultation_booked"))
    if stage_key == "consultation_done":
        return bool(participant_row.get("_consultation_done"))
    return False


def _bottleneck_label(stage_key: str) -> str:
    for key, label in _STAGE_DEFS:
        if key == stage_key:
            return label
    return stage_key.replace("_", " ").title()


def compute_participant_progress_payload(
    *,
    engagement_type_code: str | None,
    engagement_consultations: Any,
    completeness_participants: list[dict[str, Any]],
    consultations_by_user: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    stage_keys = stage_keys_for_engagement_type(engagement_type_code)
    offered_types = _offered_consultation_types(engagement_consultations)

    participants_out: list[dict[str, Any]] = []
    summary_counts = {key: 0 for key in stage_keys}

    for row in completeness_participants:
        uid = int(row["user_id"])
        q_state = str(row.get("questionnaire_state") or "not_started")
        cons_map = consultations_by_user.get(uid) or {}
        booked, done = _consultation_flags(cons_map, offered_types)

        work_row = {
            **row,
            "_consultation_booked": booked,
            "_consultation_done": done,
        }

        stages: dict[str, bool] = {}
        bottleneck: str | None = None
        for key in stage_keys:
            complete = _stage_complete(key, participant_row=work_row, q_state=q_state)
            stages[key] = complete
            if complete:
                summary_counts[key] += 1
            elif bottleneck is None:
                bottleneck = key

        participants_out.append(
            {
                "user_id": uid,
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "phone": row.get("phone"),
                "email": row.get("email"),
                "questionnaire_state": q_state,
                "stages": stages,
                "bottleneck": bottleneck,
                "bottleneck_label": _bottleneck_label(bottleneck) if bottleneck else None,
            }
        )

    stage_labels = {key: label for key, label in _STAGE_DEFS if key in stage_keys}
    total = len(participants_out)

    summary_by_stage: dict[str, dict[str, int]] = {}
    for key in stage_keys:
        applicable = 0
        complete = 0
        pending = 0
        not_applicable = 0
        for p in participants_out:
            if key in ("consultation_booked", "consultation_done"):
                offered = offered_types
                cons_map = consultations_by_user.get(int(p["user_id"])) or {}
                _, _, na = consultation_stage_statuses(cons_map, offered)
                if na:
                    not_applicable += 1
                    continue
                applicable += 1
                if p["stages"].get(key):
                    complete += 1
                else:
                    pending += 1
            else:
                applicable += 1
                if p["stages"].get(key):
                    complete += 1
                else:
                    pending += 1
        summary_by_stage[key] = {
            "complete": complete,
            "applicable": applicable,
            "pending": pending,
            "not_applicable": not_applicable,
            "failed": 0,
        }
        summary_counts[key] = complete

    return {
        "engagement_type_code": engagement_type_code,
        "stage_keys": stage_keys,
        "stage_labels": stage_labels,
        "stage_meta": {
            "bio_ai_json": {
                "source": "individual_health_report.reports AND has_blood_values",
            },
            "consultation_booked": {
                "source": "consultation_bookings want=true + date/slot/cabin",
            },
            "consultation_done": {
                "source": "consultation done flag or consultation_summary",
            },
        },
        "summary": {
            "total_participants": total,
            "stage_counts": summary_counts,
            "by_stage": summary_by_stage,
        },
        "participants": participants_out,
    }
