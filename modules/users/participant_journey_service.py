"""Employee read-only views of a participant's assessments and questionnaire state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.assessments.repository import AssessmentsRepository
from modules.engagements.blood_bookings_repository import blood_bookings_to_api_list
from modules.engagements.models import Engagement, EngagementParticipant, ParticipantBloodBooking
from modules.experts.models import ConsultationBooking
from modules.notifications.models import NotificationService
from modules.notifications.repository import NotificationsRepository
from modules.payments.models import Booking, Payment
from modules.questionnaire.models import QuestionnaireResponse
from modules.questionnaire.repository import QuestionnaireRepository
from modules.questionnaire.service import QuestionnaireService
from modules.reports.blood_report_archival import is_archived_blood_report_url
from modules.support.models import SupportTicket
from modules.users.repository import UsersRepository


def _dt_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


class ParticipantJourneyService:
    def __init__(
        self,
        users_repository: UsersRepository,
        assessments_repository: AssessmentsRepository,
        questionnaire_repository: QuestionnaireRepository,
        questionnaire_service: QuestionnaireService,
        notifications_repository: NotificationsRepository | None = None,
    ) -> None:
        self._users_repository = users_repository
        self._assessments_repository = assessments_repository
        self._questionnaire_repository = questionnaire_repository
        self._questionnaire_service = questionnaire_service
        self._notifications_repository = notifications_repository or NotificationsRepository()

    def _ensure_employee_access(self, employee) -> None:
        if employee is None:
            raise AppError(
                status_code=403,
                error_code="FORBIDDEN",
                message="You do not have permission to perform this action",
            )

    async def _ensure_user_exists(self, db: AsyncSession, user_id: int) -> None:
        user = await self._users_repository.get_user_by_id(db, user_id)
        if user is None:
            raise AppError(status_code=404, error_code="USER_NOT_FOUND", message="User does not exist")

    async def _build_category_progress(
        self,
        db: AsyncSession,
        *,
        assessment_instance_id: int,
        package_id: int,
        user_id: int,
    ) -> list[dict]:
        """Package categories plus any extra progress rows, with live has_responses.

        Progress rows are only created when a category is completed (or when an
        instance is first assigned). Categories added to a package later — or
        Metsights imports that are only partial — would otherwise be omitted,
        so the admin journey table would keep showing "not started".
        """
        progress_rows = await self._assessments_repository.list_category_progress_for_instance(
            db, assessment_instance_id=assessment_instance_id
        )
        package_links = await self._assessments_repository.list_package_categories(
            db, package_id=package_id
        )
        progress_by_id = {int(pr.category_id): pr for pr in progress_rows}

        category_ids: list[int] = []
        seen: set[int] = set()
        for link in package_links:
            cid = int(link.category_id)
            if cid not in seen:
                seen.add(cid)
                category_ids.append(cid)
        for pr in progress_rows:
            cid = int(pr.category_id)
            if cid not in seen:
                seen.add(cid)
                category_ids.append(cid)

        category_progress: list[dict] = []
        for cid in category_ids:
            cat = await self._questionnaire_repository.get_category_by_id(db, cid)
            pr = progress_by_id.get(cid)
            has_resp = (
                await self._assessments_repository.count_responses_by_category_for_instance(
                    db,
                    assessment_instance_id=assessment_instance_id,
                    category_id=cid,
                )
                > 0
            )
            status = (pr.status if pr else "incomplete") or "incomplete"
            unanswered: list[dict] = []
            if has_resp and (status or "").strip().lower() != "complete":
                unanswered = await self._questionnaire_service.list_unanswered_questions(
                    db,
                    assessment_instance_id=assessment_instance_id,
                    category_id=cid,
                    user_id=user_id,
                )
            category_progress.append(
                {
                    "category_id": cid,
                    "display_name": getattr(cat, "display_name", None) if cat else None,
                    "category_key": getattr(cat, "category_key", None) if cat else None,
                    "category_of": getattr(cat, "category_of", None) if cat else None,
                    "status": status,
                    "is_submitted": bool(pr.is_submitted) if pr else False,
                    "has_responses": has_resp,
                    "completed_at": _dt_iso(pr.completed_at) if pr else None,
                    "unanswered": unanswered,
                }
            )
        return category_progress

    async def get_summary(
        self,
        db: AsyncSession,
        *,
        employee,
        user_id: int,
        page: int,
        limit: int,
    ) -> tuple[dict, dict]:
        self._ensure_employee_access(employee)
        await self._ensure_user_exists(db, user_id)

        total = await self._assessments_repository.count_instances_for_user(db, user_id=user_id)
        rows = await self._assessments_repository.list_instances_for_user_with_engagement(
            db, user_id=user_id, page=page, limit=limit
        )

        instance_ids = [instance.assessment_instance_id for instance, _, _ in rows]
        ihr_by_instance = await self._notifications_repository.get_health_reports_for_instances(
            db, assessment_instance_ids=instance_ids
        )

        instances_out: list[dict] = []
        for instance, package, engagement in rows:
            responses = await self._questionnaire_repository.list_responses_for_instance(
                db,
                assessment_instance_id=instance.assessment_instance_id,
                category_id=None,
            )
            response_count = len(responses)
            cat_ids_touched: set[int] = set()
            for r in responses:
                for cid in (r.category_ids or []):
                    cat_ids_touched.add(cid)
            categories_touched = len(cat_ids_touched)

            category_progress = await self._build_category_progress(
                db,
                assessment_instance_id=instance.assessment_instance_id,
                package_id=int(instance.package_id),
                user_id=int(instance.user_id),
            )

            ihr = ihr_by_instance.get(instance.assessment_instance_id)
            from modules.reports.blood_booking_reports import get_current_report_root

            blood_root = await get_current_report_root(
                db,
                user_id=int(instance.user_id),
                engagement_id=int(instance.engagement_id),
            )
            has_blood = bool(
                blood_root
                and is_archived_blood_report_url((blood_root.diagnostic_report_url or "").strip())
            )
            type_code = (getattr(package, "assessment_type_code", None) or "").strip()
            has_report_url = bool((ihr.report_url or "").strip()) if ihr else False
            has_bio = has_report_url and type_code in ("1", "2")
            has_fitprint = has_report_url and type_code == "7"
            record_id = (instance.metsights_record_id or "").strip()
            bio_ai_report_available = has_bio or (type_code in ("1", "2") and bool(record_id))

            instances_out.append(
                {
                    "assessment_instance_id": instance.assessment_instance_id,
                    "status": instance.status,
                    "assigned_at": _dt_iso(instance.assigned_at),
                    "completed_at": _dt_iso(instance.completed_at),
                    "metsights_record_id": record_id or None,
                    "package_id": instance.package_id,
                    "package_code": getattr(package, "package_code", None) if package else None,
                    "package_display_name": getattr(package, "display_name", None) if package else None,
                    "assessment_type_code": type_code or None,
                    "engagement_id": instance.engagement_id,
                    "engagement_name": getattr(engagement, "engagement_name", None) if engagement else None,
                    "engagement_code": getattr(engagement, "engagement_code", None) if engagement else None,
                    "has_blood_report_url": has_blood,
                    "has_bio_ai_report_url": has_bio,
                    "bio_ai_report_available": bio_ai_report_available,
                    "has_fitprint_report_url": has_fitprint,
                    "category_progress": category_progress,
                    "questionnaire": {
                        "response_count": response_count,
                        "categories_touched": categories_touched,
                    },
                }
            )

        data = {"instances": instances_out}
        meta = {"page": page, "limit": limit, "total": total}
        return data, meta

    async def _list_payments_for_user(self, db: AsyncSession, *, user_id: int) -> list[dict[str, Any]]:
        result = await db.execute(
            select(Booking)
            .where(Booking.user_id == user_id)
            .order_by(Booking.booking_id.desc())
            .limit(200)
        )
        bookings = list(result.scalars().all())
        if not bookings:
            return []

        booking_ids = [int(b.booking_id) for b in bookings]
        pay_result = await db.execute(
            select(Payment)
            .where(Payment.booking_id.in_(booking_ids))
            .order_by(Payment.payment_id.desc())
        )
        payment_by_booking: dict[int, Payment] = {}
        for pay in pay_result.scalars().all():
            bid = int(pay.booking_id)
            if bid not in payment_by_booking:
                payment_by_booking[bid] = pay

        items: list[dict[str, Any]] = []
        for booking in bookings:
            booked_ts = booking.booked_at
            if booked_ts is not None and booked_ts.tzinfo is None:
                booked_ts = booked_ts.replace(tzinfo=timezone.utc)
            booked_at_str = (
                booked_ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                if booked_ts
                else None
            )
            pay = payment_by_booking.get(int(booking.booking_id))
            meta = booking.metadata_ if isinstance(booking.metadata_, dict) else {}
            engagement_id = meta.get("engagement_id")
            try:
                engagement_id_int = int(engagement_id) if engagement_id is not None else None
            except (TypeError, ValueError):
                engagement_id_int = None
            items.append(
                {
                    "booking_id": booking.booking_id,
                    "entity_type": booking.entity_type,
                    "entity_id": booking.entity_id,
                    "entity_name": booking.entity_name,
                    "amount_paise": booking.amount_paise,
                    "currency": booking.currency or "INR",
                    "status": booking.status,
                    "payment_status": pay.status if pay else None,
                    "payment_method": pay.payment_method if pay else None,
                    "booked_at": booked_at_str,
                    "engagement_id": engagement_id_int,
                }
            )
        return items

    async def _list_enrollments_for_user(
        self, db: AsyncSession, *, user_id: int
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            select(EngagementParticipant, Engagement)
            .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
            .where(EngagementParticipant.user_id == user_id)
            .order_by(EngagementParticipant.engagement_participant_id.desc())
        )
        seen: set[int] = set()
        enrollments: list[dict[str, Any]] = []
        for participant, engagement in result.all():
            eid = int(engagement.engagement_id)
            if eid in seen:
                continue
            seen.add(eid)
            enrollments.append(
                {
                    "engagement_id": eid,
                    "engagement_name": engagement.engagement_name,
                    "engagement_code": engagement.engagement_code,
                }
            )
        return enrollments

    async def _list_blood_bookings_for_user(
        self, db: AsyncSession, *, user_id: int
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            select(ParticipantBloodBooking, EngagementParticipant, Engagement)
            .join(
                EngagementParticipant,
                EngagementParticipant.engagement_participant_id
                == ParticipantBloodBooking.engagement_participant_id,
            )
            .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
            .where(EngagementParticipant.user_id == user_id)
            .order_by(ParticipantBloodBooking.id.desc())
            .limit(200)
        )
        items: list[dict[str, Any]] = []
        for row, participant, engagement in result.all():
            base = blood_bookings_to_api_list([row])[0]
            base["engagement_id"] = engagement.engagement_id
            base["engagement_name"] = engagement.engagement_name
            base["engagement_code"] = engagement.engagement_code
            base["engagement_participant_id"] = participant.engagement_participant_id
            items.append(base)
        return items

    async def _list_consultations_for_user(
        self, db: AsyncSession, *, user_id: int
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            select(ConsultationBooking, EngagementParticipant, Engagement)
            .join(
                EngagementParticipant,
                EngagementParticipant.engagement_participant_id
                == ConsultationBooking.engagement_participant_id,
            )
            .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
            .where(EngagementParticipant.user_id == user_id)
            .order_by(ConsultationBooking.consultation_id.desc())
            .limit(200)
        )
        items: list[dict[str, Any]] = []
        for booking, _participant, engagement in result.all():
            date_val = booking.consultation_date.isoformat() if booking.consultation_date else None
            items.append(
                {
                    "consultation_id": booking.consultation_id,
                    "engagement_id": engagement.engagement_id,
                    "engagement_name": engagement.engagement_name,
                    "engagement_code": engagement.engagement_code,
                    "expert_type": booking.expert_type,
                    "expert_id": booking.expert_id,
                    "want": bool(booking.want),
                    "date": date_val,
                    "cabin": booking.consultation_cabin,
                    "slot": booking.consultation_slot,
                    "done": bool(booking.done),
                }
            )
        return items

    async def _list_notifications_for_user(
        self, db: AsyncSession, *, user_id: int
    ) -> list[dict[str, Any]]:
        rows = await self._notifications_repository.list_notifications(
            db, page=1, limit=100, user_id=user_id
        )
        if not rows:
            return []
        service_keys = list({n.service_key for n in rows})
        services = await self._notifications_repository.get_services_by_keys(
            db, service_keys=service_keys
        )
        service_by_key = {s.service_key: s for s in services}
        items: list[dict[str, Any]] = []
        for n in rows:
            svc: NotificationService | None = service_by_key.get(n.service_key)
            message = (n.message or "").strip()
            if len(message) > 160:
                message = message[:157] + "…"
            items.append(
                {
                    "notification_id": n.notification_id,
                    "service_key": n.service_key,
                    "service_display_name": svc.display_name if svc else n.service_key,
                    "status": n.status,
                    "channel": n.channel,
                    "engagement_id": n.engagement_id,
                    "assessment_instance_id": n.assessment_instance_id,
                    "message": message or None,
                    "dispatched_at": _dt_iso(n.dispatched_at),
                    "completed_at": _dt_iso(n.completed_at),
                }
            )
        return items

    async def _list_tickets_for_user(self, db: AsyncSession, *, user_id: int) -> list[dict[str, Any]]:
        result = await db.execute(
            select(SupportTicket)
            .where(SupportTicket.user_id == user_id)
            .order_by(SupportTicket.ticket_id.desc())
            .limit(100)
        )
        items: list[dict[str, Any]] = []
        for ticket in result.scalars().all():
            query = (ticket.query_text or "").strip()
            if len(query) > 160:
                query = query[:157] + "…"
            items.append(
                {
                    "ticket_id": ticket.ticket_id,
                    "status": ticket.status,
                    "contact_input": ticket.contact_input,
                    "query_text": query,
                    "created_at": _dt_iso(ticket.created_at),
                }
            )
        return items

    async def _list_report_links_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        assessment_instances: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        from modules.reports.blood_booking_reports import get_current_report_root

        instance_ids = [int(i["assessment_instance_id"]) for i in assessment_instances]
        ihr_by_instance = await self._notifications_repository.get_health_reports_for_instances(
            db, assessment_instance_ids=instance_ids
        )

        reports: list[dict[str, Any]] = []
        seen_blood_keys: set[tuple[int, int]] = set()

        for inst in assessment_instances:
            engagement_id = int(inst["engagement_id"])
            assessment_instance_id = int(inst["assessment_instance_id"])
            engagement_name = inst.get("engagement_name")
            engagement_code = inst.get("engagement_code")
            type_code = (inst.get("assessment_type_code") or "").strip()

            blood_key = (user_id, engagement_id)
            if blood_key not in seen_blood_keys:
                seen_blood_keys.add(blood_key)
                blood_root = await get_current_report_root(
                    db, user_id=user_id, engagement_id=engagement_id
                )
                blood_url = (
                    (blood_root.diagnostic_report_url or "").strip() if blood_root else ""
                )
                if blood_url and is_archived_blood_report_url(blood_url):
                    reports.append(
                        {
                            "report_type": "blood",
                            "label": "Blood report",
                            "url": blood_url,
                            "engagement_id": engagement_id,
                            "engagement_name": engagement_name,
                            "engagement_code": engagement_code,
                            "assessment_instance_id": assessment_instance_id,
                        }
                    )

            ihr = ihr_by_instance.get(assessment_instance_id)
            report_url = ((ihr.report_url or "").strip() if ihr else "") or ""
            if report_url and type_code in ("1", "2"):
                reports.append(
                    {
                        "report_type": "bio_ai",
                        "label": "BioAI report",
                        "url": report_url,
                        "engagement_id": engagement_id,
                        "engagement_name": engagement_name,
                        "engagement_code": engagement_code,
                        "assessment_instance_id": assessment_instance_id,
                    }
                )
            elif report_url and type_code == "7":
                reports.append(
                    {
                        "report_type": "fitprint",
                        "label": "FitPrint report",
                        "url": report_url,
                        "engagement_id": engagement_id,
                        "engagement_name": engagement_name,
                        "engagement_code": engagement_code,
                        "assessment_instance_id": assessment_instance_id,
                    }
                )
            elif report_url:
                reports.append(
                    {
                        "report_type": "health",
                        "label": "Health report",
                        "url": report_url,
                        "engagement_id": engagement_id,
                        "engagement_name": engagement_name,
                        "engagement_code": engagement_code,
                        "assessment_instance_id": assessment_instance_id,
                    }
                )

        return reports

    async def get_overview(
        self,
        db: AsyncSession,
        *,
        employee,
        user_id: int,
    ) -> dict[str, Any]:
        """Full participant journey grouped by engagement, plus account-wide items."""
        summary, _meta = await self.get_summary(
            db, employee=employee, user_id=user_id, page=1, limit=100
        )
        instances = summary.get("instances") or []

        enrollments = await self._list_enrollments_for_user(db, user_id=user_id)
        payments = await self._list_payments_for_user(db, user_id=user_id)
        blood_bookings = await self._list_blood_bookings_for_user(db, user_id=user_id)
        consultations = await self._list_consultations_for_user(db, user_id=user_id)
        notifications = await self._list_notifications_for_user(db, user_id=user_id)
        tickets = await self._list_tickets_for_user(db, user_id=user_id)
        reports = await self._list_report_links_for_user(
            db, user_id=user_id, assessment_instances=instances
        )

        # Include blood report URLs from bookings not already covered via assessments.
        seen_blood_urls = {
            (r.get("engagement_id"), (r.get("url") or "").strip())
            for r in reports
            if r.get("report_type") == "blood"
        }
        for bb in blood_bookings:
            url = (bb.get("diagnostic_report_url") or "").strip()
            if not url or not is_archived_blood_report_url(url):
                continue
            key = (bb.get("engagement_id"), url)
            if key in seen_blood_urls:
                continue
            seen_blood_urls.add(key)
            reports.append(
                {
                    "report_type": "blood",
                    "label": "Blood report",
                    "url": url,
                    "engagement_id": bb.get("engagement_id"),
                    "engagement_name": bb.get("engagement_name"),
                    "engagement_code": bb.get("engagement_code"),
                    "assessment_instance_id": None,
                }
            )

        engagement_meta: dict[int, dict[str, Any]] = {}
        for e in enrollments:
            eid = int(e["engagement_id"])
            engagement_meta[eid] = {
                "engagement_id": eid,
                "engagement_name": e.get("engagement_name"),
                "engagement_code": e.get("engagement_code"),
            }

        def _ensure_engagement(eid: int, *, name: Any = None, code: Any = None) -> None:
            if eid not in engagement_meta:
                engagement_meta[eid] = {
                    "engagement_id": eid,
                    "engagement_name": name,
                    "engagement_code": code,
                }
            else:
                if name and not engagement_meta[eid].get("engagement_name"):
                    engagement_meta[eid]["engagement_name"] = name
                if code and not engagement_meta[eid].get("engagement_code"):
                    engagement_meta[eid]["engagement_code"] = code

        for inst in instances:
            _ensure_engagement(
                int(inst["engagement_id"]),
                name=inst.get("engagement_name"),
                code=inst.get("engagement_code"),
            )
        for row in blood_bookings:
            _ensure_engagement(
                int(row["engagement_id"]),
                name=row.get("engagement_name"),
                code=row.get("engagement_code"),
            )
        for row in consultations:
            _ensure_engagement(
                int(row["engagement_id"]),
                name=row.get("engagement_name"),
                code=row.get("engagement_code"),
            )
        for row in reports:
            if row.get("engagement_id") is not None:
                _ensure_engagement(
                    int(row["engagement_id"]),
                    name=row.get("engagement_name"),
                    code=row.get("engagement_code"),
                )
        for row in notifications:
            if row.get("engagement_id") is not None:
                _ensure_engagement(int(row["engagement_id"]))
        for row in payments:
            if row.get("engagement_id") is not None:
                _ensure_engagement(int(row["engagement_id"]))

        buckets: dict[int, dict[str, Any]] = {}
        for eid, meta_row in engagement_meta.items():
            buckets[eid] = {
                **meta_row,
                "assessments": {"instances": [], "meta": {"page": 1, "limit": 100, "total": 0}},
                "payments": [],
                "blood_bookings": [],
                "reports": [],
                "consultations": [],
                "notifications": [],
            }

        for inst in instances:
            eid = int(inst["engagement_id"])
            buckets[eid]["assessments"]["instances"].append(inst)
        for eid, bucket in buckets.items():
            total = len(bucket["assessments"]["instances"])
            bucket["assessments"]["meta"] = {"page": 1, "limit": 100, "total": total}

        account_payments: list[dict[str, Any]] = []
        account_notifications: list[dict[str, Any]] = []

        for row in payments:
            eid = row.get("engagement_id")
            if eid is not None and int(eid) in buckets:
                buckets[int(eid)]["payments"].append(row)
            else:
                account_payments.append(row)

        for row in blood_bookings:
            buckets[int(row["engagement_id"])]["blood_bookings"].append(row)

        for row in reports:
            eid = row.get("engagement_id")
            if eid is not None and int(eid) in buckets:
                buckets[int(eid)]["reports"].append(row)

        for row in consultations:
            buckets[int(row["engagement_id"])]["consultations"].append(row)

        for row in notifications:
            eid = row.get("engagement_id")
            if eid is not None and int(eid) in buckets:
                buckets[int(eid)]["notifications"].append(row)
            else:
                account_notifications.append(row)

        engagements_out = sorted(
            buckets.values(),
            key=lambda e: int(e["engagement_id"]),
            reverse=True,
        )

        return {
            "engagements": engagements_out,
            "account": {
                "payments": account_payments,
                "notifications": account_notifications,
                "tickets": tickets,
            },
        }

    async def get_instance_detail(
        self,
        db: AsyncSession,
        *,
        employee,
        user_id: int,
        assessment_instance_id: int,
    ) -> dict:
        self._ensure_employee_access(employee)
        await self._ensure_user_exists(db, user_id)

        row = await self._assessments_repository.get_instance_for_user_with_engagement(
            db,
            assessment_instance_id=assessment_instance_id,
            user_id=user_id,
        )
        if row is None:
            raise AppError(
                status_code=404,
                error_code="ASSESSMENT_NOT_FOUND",
                message="Assessment instance does not exist for this user",
            )

        instance, package, engagement = row

        responses = await self._questionnaire_repository.list_responses_for_instance(
            db,
            assessment_instance_id=assessment_instance_id,
            category_id=None,
        )
        resp_by_qid: dict[int, QuestionnaireResponse] = {}
        for r in responses:
            resp_by_qid[int(r.question_id)] = r

        category_progress = await self._build_category_progress(
            db,
            assessment_instance_id=assessment_instance_id,
            package_id=int(instance.package_id),
            user_id=int(instance.user_id),
        )
        cat_progress_map = {int(c["category_id"]): c for c in category_progress}

        ordered_category_ids = await self._assessments_repository.get_assigned_category_ids_for_package_ordered(
            db, package_id=instance.package_id
        )

        categories_out: list[dict] = []
        for category_id in ordered_category_ids:
            cat = await self._questionnaire_repository.get_category_by_id(db, category_id)
            questions = await self._questionnaire_service.list_category_questions_for_user(
                db, category_id=category_id
            )
            cat_pr = cat_progress_map.get(category_id)
            cat_is_submitted = bool(cat_pr["is_submitted"]) if cat_pr else False

            questions_out: list[dict] = []
            for q in questions:
                qid = int(q["question_id"])
                resp_obj = resp_by_qid.get(qid)
                if resp_obj is None:
                    answer_state = "empty"
                    answer = None
                else:
                    answer = resp_obj.answer
                    answer_state = "submitted" if cat_is_submitted else "draft"

                payload = {**q}
                payload["answer"] = answer
                payload["answer_state"] = answer_state
                questions_out.append(payload)

            categories_out.append(
                {
                    "category_id": category_id,
                    "display_name": getattr(cat, "display_name", None) if cat else None,
                    "category_key": getattr(cat, "category_key", None) if cat else None,
                    "questions": questions_out,
                }
            )

        return {
            "assessment_instance_id": instance.assessment_instance_id,
            "user_id": instance.user_id,
            "status": instance.status,
            "assigned_at": _dt_iso(instance.assigned_at),
            "completed_at": _dt_iso(instance.completed_at),
            "package": {
                "package_id": instance.package_id,
                "package_code": getattr(package, "package_code", None) if package else None,
                "package_display_name": getattr(package, "display_name", None) if package else None,
            },
            "engagement": {
                "engagement_id": instance.engagement_id,
                "engagement_name": getattr(engagement, "engagement_name", None) if engagement else None,
                "engagement_code": getattr(engagement, "engagement_code", None) if engagement else None,
            },
            "category_progress": category_progress,
            "categories": categories_out,
        }
