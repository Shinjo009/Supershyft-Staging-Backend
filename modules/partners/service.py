"""Partners service — CRUD business rules."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.audit.service import AuditService
from modules.employee.access_control import ensure_admin
from modules.employee.repository import EmployeeRepository
from modules.employee.service import EmployeeContext
from modules.experts.models import Expert
from modules.experts.repository import ExpertsRepository
from modules.experts.service import ExpertTypesService
from modules.partners.models import Partner, PartnerRole
from modules.partners.repository import PartnersRepository
from modules.partners.role_utils import partner_role_value
from modules.partners.schemas import PartnerCreateRequest, PartnerExpertProfileIn, PartnerUpdateRequest


_ALLOWED_STATUS = {"active", "inactive", "archived"}
_ALLOWED_STATUS_UPDATE = {"active", "inactive"}
_ALLOWED_ROLES = frozenset(
    {
        PartnerRole.phlebo.value,
        PartnerRole.expert.value,
        PartnerRole.organization_manager.value,
    }
)


def _normalize_status(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class PartnersService:
    def __init__(
        self,
        repository: PartnersRepository,
        audit_service: AuditService | None = None,
        employee_repository: EmployeeRepository | None = None,
        experts_repository: ExpertsRepository | None = None,
        expert_types_service: ExpertTypesService | None = None,
    ):
        self._repository = repository
        self._audit_service = audit_service
        self._employee_repository = employee_repository or EmployeeRepository()
        self._experts_repository = experts_repository or ExpertsRepository()
        self._expert_types_service = expert_types_service

    def _require_audit(self) -> AuditService:
        if self._audit_service is None:
            raise RuntimeError("Audit service is required")
        return self._audit_service

    async def _reject_if_employee_identifier_exists(
        self,
        db: AsyncSession,
        *,
        phone: str | None,
        email: str | None,
    ) -> None:
        if phone:
            existing = await self._employee_repository.get_by_phone(db, phone)
            if existing is not None:
                raise AppError(
                    status_code=409,
                    error_code="IDENTIFIER_ALREADY_EXISTS",
                    message="Phone or email already exists on an employee",
                )
        if email:
            existing = await self._employee_repository.get_by_email(db, email)
            if existing is not None:
                raise AppError(
                    status_code=409,
                    error_code="IDENTIFIER_ALREADY_EXISTS",
                    message="Phone or email already exists on an employee",
                )

    def _role_value(self, role: PartnerRole | str) -> str:
        return role.value if isinstance(role, PartnerRole) else str(role)

    def _require_expert_types(self) -> ExpertTypesService:
        if self._expert_types_service is None:
            raise RuntimeError("Expert types service is required for expert partners")
        return self._expert_types_service

    async def _create_expert_profile_for_partner(
        self,
        db: AsyncSession,
        *,
        partner_id: int,
        profile: PartnerExpertProfileIn,
        ip_address: str,
        user_agent: str,
        endpoint: str,
    ) -> Expert:
        existing = await self._experts_repository.get_by_partner_id(db, partner_id)
        if existing is not None:
            return existing

        await self._require_expert_types().validate_type_key(db, profile.expert_type)
        expert = Expert(
            partner_id=partner_id,
            expert_type=profile.expert_type,
            specialization=profile.specialization.strip(),
            status="active",
        )
        expert = await self._experts_repository.create(db, expert)
        await self._require_audit().log_event(
            db,
            action="EMPLOYEE_CREATE_EXPERT",
            endpoint=endpoint,
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=None,
            session_id=None,
        )
        return expert

    async def create_partner(
        self,
        db: AsyncSession,
        *,
        employee: EmployeeContext,
        payload: PartnerCreateRequest,
        ip_address: str,
        user_agent: str,
        endpoint: str,
    ) -> tuple[Partner, int | None]:
        ensure_admin(employee)

        status_value = _normalize_status(payload.status)
        if status_value not in _ALLOWED_STATUS:
            raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")

        phone = _normalize_phone(payload.phone)
        email = _normalize_email(str(payload.email) if payload.email else None)
        role = payload.role.value if isinstance(payload.role, PartnerRole) else str(payload.role)

        await self._reject_if_employee_identifier_exists(db, phone=phone, email=email)

        if phone:
            existing = await self._repository.get_by_phone(db, phone)
            if existing is not None:
                raise AppError(status_code=409, error_code="PARTNER_ALREADY_EXISTS", message="Partner already exists")
        if email:
            existing = await self._repository.get_by_email(db, email)
            if existing is not None:
                raise AppError(status_code=409, error_code="PARTNER_ALREADY_EXISTS", message="Partner already exists")

        row = Partner(
            name=payload.name.strip(),
            phone=phone,
            email=email,
            role=role,
            status=status_value,
        )
        try:
            row = await self._repository.create(db, row)
        except IntegrityError as exc:
            raise AppError(
                status_code=409,
                error_code="PARTNER_ALREADY_EXISTS",
                message="Partner already exists",
            ) from exc

        await self._require_audit().log_event(
            db,
            action="PARTNER_CREATE",
            endpoint=endpoint,
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=None,
            session_id=None,
        )

        expert_id: int | None = None
        if role == PartnerRole.expert.value and payload.expert_profile is not None:
            expert = await self._create_expert_profile_for_partner(
                db,
                partner_id=row.partner_id,
                profile=payload.expert_profile,
                ip_address=ip_address,
                user_agent=user_agent,
                endpoint=endpoint,
            )
            expert_id = expert.expert_id
        return row, expert_id

    async def list_partners(
        self,
        db: AsyncSession,
        *,
        employee: EmployeeContext,
        page: int,
        limit: int,
        status: str | None,
        role: str | None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ) -> tuple[list[Partner], int]:
        ensure_admin(employee)

        status_value = None
        if status is not None:
            normalized = _normalize_status(status)
            if normalized not in _ALLOWED_STATUS:
                raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")
            status_value = normalized

        role_value = None
        if role is not None:
            normalized_role = role.strip().lower()
            if normalized_role not in _ALLOWED_ROLES:
                raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")
            role_value = normalized_role

        partners = await self._repository.list_partners(
            db,
            page=page,
            limit=limit,
            status=status_value,
            role=role_value,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        total = await self._repository.count_partners(
            db, status=status_value, role=role_value, search=search
        )
        return partners, total

    async def get_partner_details(
        self,
        db: AsyncSession,
        *,
        employee: EmployeeContext,
        partner_id: int,
    ) -> tuple[Partner, int | None]:
        ensure_admin(employee)
        row = await self._repository.get_by_id(db, partner_id)
        if row is None:
            raise AppError(status_code=404, error_code="PARTNER_NOT_FOUND", message="Partner does not exist")
        expert = await self._experts_repository.get_by_partner_id(db, partner_id)
        return row, expert.expert_id if expert is not None else None

    async def update_partner(
        self,
        db: AsyncSession,
        *,
        employee: EmployeeContext,
        partner_id: int,
        payload: PartnerUpdateRequest,
        ip_address: str,
        user_agent: str,
        endpoint: str,
    ) -> tuple[Partner, int | None]:
        ensure_admin(employee)
        row = await self._repository.get_by_id(db, partner_id)
        if row is None:
            raise AppError(status_code=404, error_code="PARTNER_NOT_FOUND", message="Partner does not exist")

        phone = _normalize_phone(payload.phone)
        email = _normalize_email(str(payload.email) if payload.email else None)
        role = self._role_value(payload.role)

        existing_expert = await self._experts_repository.get_by_partner_id(db, partner_id)
        current_role = partner_role_value(row.role)
        if (
            role != PartnerRole.expert.value
            and existing_expert is not None
            and role != current_role
        ):
            raise AppError(
                status_code=400,
                error_code="EXPERT_PROFILE_EXISTS",
                message="Delete this partner's expert profile on the Experts page before changing role",
            )
        if role == PartnerRole.expert.value:
            if existing_expert is None and payload.expert_profile is None:
                raise AppError(
                    status_code=400,
                    error_code="INVALID_INPUT",
                    message="expert_profile is required when role is expert and no expert profile exists",
                )
        elif payload.expert_profile is not None:
            raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")

        await self._reject_if_employee_identifier_exists(db, phone=phone, email=email)

        if phone:
            existing = await self._repository.get_by_phone(db, phone)
            if existing is not None and existing.partner_id != row.partner_id:
                raise AppError(status_code=409, error_code="PARTNER_ALREADY_EXISTS", message="Partner already exists")
        if email:
            existing = await self._repository.get_by_email(db, email)
            if existing is not None and existing.partner_id != row.partner_id:
                raise AppError(status_code=409, error_code="PARTNER_ALREADY_EXISTS", message="Partner already exists")

        row.name = payload.name.strip()
        row.phone = phone
        row.email = email
        row.role = role
        try:
            row = await self._repository.update(db, row)
        except IntegrityError as exc:
            raise AppError(
                status_code=409,
                error_code="PARTNER_ALREADY_EXISTS",
                message="Partner already exists",
            ) from exc

        await self._require_audit().log_event(
            db,
            action="PARTNER_UPDATE",
            endpoint=endpoint,
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=None,
            session_id=None,
        )

        expert_id: int | None = existing_expert.expert_id if existing_expert is not None else None
        if (
            role == PartnerRole.expert.value
            and existing_expert is None
            and payload.expert_profile is not None
        ):
            expert = await self._create_expert_profile_for_partner(
                db,
                partner_id=row.partner_id,
                profile=payload.expert_profile,
                ip_address=ip_address,
                user_agent=user_agent,
                endpoint=endpoint,
            )
            expert_id = expert.expert_id
        return row, expert_id

    async def change_partner_status(
        self,
        db: AsyncSession,
        *,
        employee: EmployeeContext,
        partner_id: int,
        status: str,
        ip_address: str,
        user_agent: str,
        endpoint: str,
    ) -> Partner:
        ensure_admin(employee)
        row = await self._repository.get_by_id(db, partner_id)
        if row is None:
            raise AppError(status_code=404, error_code="PARTNER_NOT_FOUND", message="Partner does not exist")

        normalized = _normalize_status(status)
        if normalized not in _ALLOWED_STATUS_UPDATE:
            raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")

        row.status = normalized
        row = await self._repository.update(db, row)

        await self._require_audit().log_event(
            db,
            action="PARTNER_UPDATE_STATUS",
            endpoint=endpoint,
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=None,
            session_id=None,
        )
        return row
