"""20-step camp E2E participant progress (admin ops)."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagements.enums import EngagementKind
from modules.engagements.metsights_pro_validation import BIO_AI_ENGAGEMENT_TYPE_CODES
from modules.engagements.participant_progress import (
    _offered_consultation_types,
    _questionnaire_complete,
    consultation_stage_statuses,
    stage_keys_for_engagement_type,
)
from modules.notifications.models import Notification

StageStatus = Literal["complete", "pending", "not_applicable", "failed"]

_STEP_DEFS: tuple[tuple[str, str, str], ...] = (
    ("engagement_setup", "Engagement setup verified", "precamp"),
    ("enrolled", "Enrolled", "precamp"),
    ("onboarding_notify", "Onboarding notify", "precamp"),
    ("app_camp_scheduled", "App camp scheduled", "camp"),
    ("questionnaire", "Questionnaire", "camp"),
    ("questionnaire_reminder_before", "Questionnaire reminder (before)", "comms"),
    ("pretest_guidelines", "Pretest guidelines", "comms"),
    ("booking_guide_phlebo", "Booking guide (phlebo)", "precamp"),
    ("booking_id", "Booking ID / camp blood", "lab"),
    ("blood_report", "Blood PDF", "lab"),
    ("blood_values", "Blood values", "lab"),
    ("blood_report_ready", "Blood report ready notify", "comms"),
    ("metsights_q_sync", "Metsights Q sync", "reports"),
    ("bio_ai_json", "BioAI JSON", "reports"),
    ("bio_ai_report", "BioAI PDF", "reports"),
    ("bioai_report_ready", "BioAI report ready notify", "comms"),
    ("consultation_ready", "Consultation ready notify", "comms"),
    ("consultation_booked", "Consult booked", "consult"),
    ("consultation_booking_alert", "Consult booking alert", "comms"),
    ("consultation_remainder_done", "Consult remainder + done", "consult"),
)

_EVENT_BY_STEP: dict[str, str] = {
    "onboarding_notify": "onboarding",
    "questionnaire_reminder_before": "questionnaire_reminder_before",
    "pretest_guidelines": "pretest_guidelines",
    "booking_guide_phlebo": "booking_guide",
    "blood_report_ready": "blood_report_ready",
    "bioai_report_ready": "bioai_report_ready",
    "consultation_ready": "consultation_ready",
    "consultation_booking_alert": "consultation_booking_alert",
    "consultation_remainder_done": "consultation_remainder",
}

_STAGE_META: dict[str, dict[str, str]] = {
    "engagement_setup": {
        "source": "Engagement packages, schedule, assistants, notification events",
        "type": "engagement",
    },
    "enrolled": {"source": "engagement_participants row", "type": "participant"},
    "onboarding_notify": {"source": "notifications dispatch (onboarding event)", "type": "notification"},
    "app_camp_scheduled": {"source": "engagement_date + slot_start_time", "type": "participant"},
    "questionnaire": {"source": "questionnaire_state === filled", "type": "participant"},
    "questionnaire_reminder_before": {
        "source": "notifications dispatch (questionnaire_reminder_before)",
        "type": "notification",
    },
    "pretest_guidelines": {"source": "notifications dispatch (pretest_guidelines)", "type": "notification"},
    "booking_guide_phlebo": {"source": "notifications dispatch (booking_guide)", "type": "engagement"},
    "booking_id": {"source": "has_booking_id / booking_id", "type": "participant"},
    "blood_report": {"source": "archived blood report URL", "type": "participant"},
    "blood_values": {"source": "blood test values in DB", "type": "participant"},
    "blood_report_ready": {"source": "notifications dispatch (blood_report_ready)", "type": "notification"},
    "metsights_q_sync": {
        "source": "questionnaire filled + is_profile_created_on_metsights",
        "type": "participant",
    },
    "bio_ai_json": {
        "source": "individual_health_report.reports AND has_blood_values",
        "type": "participant",
    },
    "bio_ai_report": {"source": "archived BioAI report_url", "type": "participant"},
    "bioai_report_ready": {"source": "notifications dispatch (bioai_report_ready)", "type": "notification"},
    "consultation_ready": {"source": "notifications dispatch (consultation_ready)", "type": "notification"},
    "consultation_booked": {
        "source": "consultation_bookings want=true + date/slot/cabin",
        "type": "participant",
    },
    "consultation_booking_alert": {
        "source": "notifications dispatch (consultation_booking_alert)",
        "type": "notification",
    },
    "consultation_remainder_done": {
        "source": "consultation_remainder dispatch + consultation done/summary",
        "type": "mixed",
    },
}

_GROUP_LABELS = {
    "precamp": "Pre-camp",
    "camp": "Camp",
    "lab": "Lab",
    "reports": "Reports",
    "consult": "Consult",
    "comms": "Comms",
}

# Steps that must not drive per-participant "stuck at" (camp-wide or always complete).
_PARTICIPANT_BOTTLENECK_EXCLUDE: frozenset[str] = frozenset(
    {"engagement_setup", "booking_guide_phlebo", "enrolled"}
)

_CONSULTATION_TYPE_CODES = frozenset(
    {
        EngagementKind.bio_ai_with_consultation.value,
        EngagementKind.blood_test_with_consultation.value,
        EngagementKind.consultation.value,
    }
)

_BLOOD_TYPE_CODES = frozenset(
    {
        EngagementKind.blood_test.value,
        EngagementKind.blood_test_with_consultation.value,
    }
)


def e2e_stage_keys_for_engagement_type(type_code: str | None) -> list[str]:
    code = (type_code or "").strip().lower()
    keys: list[str] = []
    for key, _, _ in _STEP_DEFS:
        if key == "engagement_setup" or key == "booking_guide_phlebo":
            keys.append(key)
            continue
        if key == "enrolled":
            keys.append(key)
            continue
        if key in {
            "onboarding_notify",
            "app_camp_scheduled",
            "questionnaire",
            "questionnaire_reminder_before",
            "pretest_guidelines",
        }:
            keys.append(key)
            continue
        if key in {"booking_id", "blood_report", "blood_values", "blood_report_ready"}:
            if code in _BLOOD_TYPE_CODES or code in BIO_AI_ENGAGEMENT_TYPE_CODES:
                keys.append(key)
            continue
        if key == "metsights_q_sync":
            if code in BIO_AI_ENGAGEMENT_TYPE_CODES or code in _BLOOD_TYPE_CODES:
                keys.append(key)
            continue
        if key in {"bio_ai_json", "bio_ai_report", "bioai_report_ready"}:
            if code in BIO_AI_ENGAGEMENT_TYPE_CODES:
                keys.append(key)
            continue
        if key in {
            "consultation_ready",
            "consultation_booked",
            "consultation_booking_alert",
            "consultation_remainder_done",
        }:
            if code in _CONSULTATION_TYPE_CODES:
                keys.append(key)
    return keys


def _stage_label(step_key: str) -> str:
    for key, label, _ in _STEP_DEFS:
        if key == step_key:
            return label
    return step_key.replace("_", " ").title()


def _entry(status: StageStatus, *, source: str | None = None, detail: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": status}
    if source:
        out["source"] = source
    if detail:
        out["detail"] = detail
    return out


def _bio_ai_json_complete(row: dict[str, Any]) -> bool:
    return bool(row.get("has_bio_ai_json")) and bool(row.get("has_blood_values"))


def _camp_scheduled(row: dict[str, Any]) -> bool:
    return bool((row.get("engagement_date") or "").strip()) and bool((row.get("slot_start_time") or "").strip())


def _metsights_sync_complete(row: dict[str, Any], q_state: str) -> bool:
    return _questionnaire_complete(q_state) and bool(row.get("is_profile_created_on_metsights"))


def _notification_status_for_user(
    *,
    user_id: int,
    service_keys: list[str],
    dispatch_map: dict[tuple[int, str], str],
) -> StageStatus:
    if not service_keys:
        return "not_applicable"
    statuses: list[str] = []
    for sk in service_keys:
        statuses.append(dispatch_map.get((user_id, sk), "none"))
    if any(s == "sent" for s in statuses):
        return "complete"
    if any(s == "failed" for s in statuses):
        return "failed"
    if any(s == "pending" for s in statuses):
        return "pending"
    return "pending"


def _engagement_notification_status(
    *,
    service_keys: list[str],
    engagement_dispatch: dict[str, str],
) -> StageStatus:
    if not service_keys:
        return "not_applicable"
    statuses = [engagement_dispatch.get(sk, "none") for sk in service_keys]
    if any(s == "sent" for s in statuses):
        return "complete"
    if any(s == "failed" for s in statuses):
        return "failed"
    if any(s == "pending" for s in statuses):
        return "pending"
    return "pending"


def _compute_engagement_setup(
    *,
    engagement: dict[str, Any],
    event_service_keys: dict[str, list[str]],
    onboarding_assistant_count: int,
) -> StageStatus:
    checks: list[bool] = []
    has_pkg = bool(engagement.get("assessment_package_id")) or bool(engagement.get("diagnostic_package_id"))
    checks.append(has_pkg)
    has_schedule = bool(engagement.get("start_date")) and bool(engagement.get("end_date"))
    if engagement.get("slot_detail"):
        has_schedule = True
    checks.append(has_schedule)
    checks.append(onboarding_assistant_count > 0)
    onboarding_keys = event_service_keys.get("onboarding") or []
    checks.append(len(onboarding_keys) > 0)
    if all(checks):
        return "complete"
    if any(checks):
        return "pending"
    return "pending"


def _status_counts(entries: list[StageStatus]) -> dict[str, int]:
    out = {"complete": 0, "pending": 0, "not_applicable": 0, "failed": 0, "applicable": 0}
    for st in entries:
        if st == "not_applicable":
            out["not_applicable"] += 1
        else:
            out["applicable"] += 1
            out[st] += 1
    return out


async def load_notification_dispatch_maps(
    db: AsyncSession,
    *,
    engagement_id: int,
    service_keys: list[str],
) -> tuple[dict[tuple[int, str], str], dict[str, str]]:
    """Return per-(user_id, service_key) status and engagement-level best status per service_key."""
    if not service_keys:
        return {}, {}

    result = await db.execute(
        select(Notification.service_key, Notification.status, Notification.user).where(
            Notification.engagement_id == engagement_id,
            Notification.service_key.in_(service_keys),
        )
    )

    per_user: dict[tuple[int, str], str] = {}
    per_engagement: dict[str, str] = {}
    priority = {"sent": 3, "failed": 2, "pending": 1, "none": 0}

    def merge(current: str, new: str) -> str:
        if priority.get(new, 0) > priority.get(current, 0):
            return new
        return current

    for service_key, status, user_blob in result.all():
        st = str(status or "pending")
        per_engagement[service_key] = merge(per_engagement.get(service_key, "none"), st)
        user_ids: list[int] = []
        if isinstance(user_blob, dict):
            raw = user_blob.get("user_ids")
            if isinstance(raw, list):
                for item in raw:
                    try:
                        user_ids.append(int(item))
                    except (TypeError, ValueError):
                        continue
        for uid in user_ids:
            key = (uid, service_key)
            per_user[key] = merge(per_user.get(key, "none"), st)

    return per_user, per_engagement


def compute_e2e_participant_progress_payload(
    *,
    engagement_type_code: str | None,
    engagement: dict[str, Any],
    engagement_consultations: Any,
    completeness_participants: list[dict[str, Any]],
    participant_extras_by_user: dict[int, dict[str, Any]],
    consultations_by_user: dict[int, dict[str, Any]],
    event_service_keys: dict[str, list[str]],
    onboarding_assistant_count: int,
    dispatch_per_user: dict[tuple[int, str], str],
    dispatch_per_engagement: dict[str, str],
) -> dict[str, Any]:
    stage_keys = e2e_stage_keys_for_engagement_type(engagement_type_code)
    offered_types = _offered_consultation_types(engagement_consultations)
    legacy_keys = stage_keys_for_engagement_type(engagement_type_code)

    setup_status = _compute_engagement_setup(
        engagement=engagement,
        event_service_keys=event_service_keys,
        onboarding_assistant_count=onboarding_assistant_count,
    )
    booking_guide_keys = event_service_keys.get("booking_guide") or []
    booking_guide_status = _engagement_notification_status(
        service_keys=booking_guide_keys,
        engagement_dispatch=dispatch_per_engagement,
    )

    stage_labels = {key: _stage_label(key) for key in stage_keys}
    stage_meta = {key: dict(_STAGE_META.get(key, {})) for key in stage_keys}

    groups_order = ["precamp", "camp", "lab", "reports", "consult", "comms"]
    stage_groups: list[dict[str, Any]] = []
    for group_key in groups_order:
        steps = [k for k, _, g in _STEP_DEFS if k in stage_keys and g == group_key]
        if steps:
            stage_groups.append({"key": group_key, "label": _GROUP_LABELS[group_key], "steps": steps})

    participants_out: list[dict[str, Any]] = []
    by_stage: dict[str, dict[str, int]] = {key: _status_counts([]) for key in stage_keys}

    for row in completeness_participants:
        uid = int(row["user_id"])
        extras = participant_extras_by_user.get(uid) or {}
        merged = {**row, **extras}
        q_state = str(row.get("questionnaire_state") or "not_started")
        cons_map = consultations_by_user.get(uid) or {}
        consult_booked, consult_done, consult_na = consultation_stage_statuses(cons_map, offered_types)

        stages: dict[str, dict[str, Any]] = {}
        bottleneck: str | None = None

        for key in stage_keys:
            meta_source = _STAGE_META.get(key, {}).get("source")
            if key == "engagement_setup":
                st = setup_status
                stages[key] = _entry(st, source=meta_source)
            elif key == "booking_guide_phlebo":
                st = booking_guide_status
                stages[key] = _entry(st, source=meta_source)
            elif key == "enrolled":
                stages[key] = _entry("complete", source=meta_source)
                st = "complete"
            elif key == "onboarding_notify":
                st = _notification_status_for_user(
                    user_id=uid,
                    service_keys=event_service_keys.get("onboarding") or [],
                    dispatch_map=dispatch_per_user,
                )
                stages[key] = _entry(st, source=meta_source)
            elif key == "app_camp_scheduled":
                st = "complete" if _camp_scheduled(merged) else "pending"
                stages[key] = _entry(st, source=meta_source)
            elif key == "questionnaire":
                st = "complete" if _questionnaire_complete(q_state) else "pending"
                stages[key] = _entry(st, source=meta_source)
            elif key in _EVENT_BY_STEP and key not in {
                "consultation_remainder_done",
                "booking_guide_phlebo",
            }:
                event_code = _EVENT_BY_STEP[key]
                st = _notification_status_for_user(
                    user_id=uid,
                    service_keys=event_service_keys.get(event_code) or [],
                    dispatch_map=dispatch_per_user,
                )
                stages[key] = _entry(st, source=meta_source)
            elif key == "booking_id":
                st = "complete" if bool(row.get("has_booking_id")) else "pending"
                stages[key] = _entry(st, source=meta_source)
            elif key == "blood_report":
                st = "complete" if bool(row.get("has_blood_report")) else "pending"
                stages[key] = _entry(st, source=meta_source)
            elif key == "blood_values":
                st = "complete" if bool(row.get("has_blood_values")) else "pending"
                stages[key] = _entry(st, source=meta_source)
            elif key == "metsights_q_sync":
                st = "complete" if _metsights_sync_complete(merged, q_state) else "pending"
                stages[key] = _entry(st, source=meta_source)
            elif key == "bio_ai_json":
                st = "complete" if _bio_ai_json_complete(row) else "pending"
                stages[key] = _entry(st, source=meta_source)
            elif key == "bio_ai_report":
                st = "complete" if bool(row.get("has_bio_ai_report")) else "pending"
                stages[key] = _entry(st, source=meta_source)
            elif key == "consultation_booked":
                if consult_na:
                    st = "not_applicable"
                else:
                    st = "complete" if consult_booked else "pending"
                stages[key] = _entry(st, source=meta_source)
            elif key == "consultation_remainder_done":
                if consult_na:
                    st = "not_applicable"
                else:
                    remainder = _notification_status_for_user(
                        user_id=uid,
                        service_keys=event_service_keys.get("consultation_remainder") or [],
                        dispatch_map=dispatch_per_user,
                    )
                    if consult_done and remainder == "complete":
                        st = "complete"
                    elif remainder == "failed":
                        st = "failed"
                    elif consult_done:
                        st = "pending"
                    else:
                        st = "pending"
                stages[key] = _entry(st, source=meta_source)
            else:
                st = "pending"
                stages[key] = _entry(st, source=meta_source)

            by_stage[key] = _merge_status_count(by_stage[key], st)

            if (
                bottleneck is None
                and key not in _PARTICIPANT_BOTTLENECK_EXCLUDE
                and st in ("pending", "failed")
            ):
                bottleneck = key

        legacy_stages: dict[str, bool] = {}
        legacy_stages["enrolled"] = True
        legacy_stages["booking_id"] = bool(row.get("has_booking_id"))
        legacy_stages["questionnaire"] = _questionnaire_complete(q_state)
        if "blood_report" in legacy_keys:
            legacy_stages["blood_report"] = bool(row.get("has_blood_report"))
            legacy_stages["blood_values"] = bool(row.get("has_blood_values"))
        if "bio_ai_json" in legacy_keys:
            legacy_stages["bio_ai_json"] = _bio_ai_json_complete(row)
            legacy_stages["bio_ai_report"] = bool(row.get("has_bio_ai_report"))
        if "consultation_booked" in legacy_keys:
            if consult_na:
                legacy_stages["consultation_booked"] = False
                legacy_stages["consultation_done"] = False
            else:
                legacy_stages["consultation_booked"] = consult_booked
                legacy_stages["consultation_done"] = consult_done

        participants_out.append(
            {
                "user_id": uid,
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "phone": row.get("phone"),
                "email": row.get("email"),
                "questionnaire_state": q_state,
                "stages": stages,
                "legacy_stages": legacy_stages,
                "bottleneck": bottleneck,
                "bottleneck_label": _stage_label(bottleneck) if bottleneck else None,
                "bottleneck_scope": "participant" if bottleneck else None,
            }
        )

    legacy_stage_counts = {key: 0 for key in legacy_keys}
    for p in participants_out:
        for key in legacy_keys:
            if p["legacy_stages"].get(key):
                legacy_stage_counts[key] += 1

    total = len(participants_out)

    bottlenecks: list[dict[str, Any]] = []
    if setup_status in ("pending", "failed") and total > 0:
        bottlenecks.append(
            {
                "key": "engagement_setup",
                "label": "Camp configuration",
                "pending": total,
                "scope": "engagement",
            }
        )
    for key in stage_keys:
        if key in _PARTICIPANT_BOTTLENECK_EXCLUDE:
            continue
        pending = by_stage[key]["pending"] + by_stage[key]["failed"]
        if pending > 0 and by_stage[key]["applicable"] > 0:
            bottlenecks.append(
                {"key": key, "label": _stage_label(key), "pending": pending, "scope": "participant"}
            )
    bottlenecks.sort(key=lambda x: x["pending"], reverse=True)
    bottlenecks = bottlenecks[:4]

    return {
        "engagement_type_code": engagement_type_code,
        "e2e_version": 1,
        "stage_keys": stage_keys,
        "stage_labels": stage_labels,
        "stage_groups": stage_groups,
        "stage_meta": stage_meta,
        "engagement_setup": {
            "engagement_setup": _entry(setup_status, source=_STAGE_META["engagement_setup"]["source"]),
            "booking_guide_phlebo": _entry(
                booking_guide_status, source=_STAGE_META["booking_guide_phlebo"]["source"]
            ),
        },
        "summary": {
            "total_participants": total,
            "by_stage": by_stage,
            "stage_counts": legacy_stage_counts,
            "bottlenecks": bottlenecks,
        },
        "participants": participants_out,
    }


def _merge_status_count(acc: dict[str, int], status: StageStatus) -> dict[str, int]:
    acc = dict(acc)
    if status == "not_applicable":
        acc["not_applicable"] += 1
    else:
        acc["applicable"] += 1
        acc[status] += 1
    return acc
