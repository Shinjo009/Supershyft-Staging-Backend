"""Partners module dependencies."""

from __future__ import annotations

from modules.audit.repository import AuditRepository
from modules.audit.service import AuditService
from modules.notifications.dependencies import get_notifications_service
from modules.partners.auth_service import PartnerAuthService
from modules.experts.dependencies import get_expert_types_service
from modules.experts.repository import ExpertsRepository
from modules.partners.repository import PartnersRepository
from modules.partners.service import PartnersService


def get_partners_service() -> PartnersService:
    return PartnersService(
        repository=PartnersRepository(),
        audit_service=AuditService(AuditRepository()),
        experts_repository=ExpertsRepository(),
        expert_types_service=get_expert_types_service(),
    )


def get_partner_auth_service() -> PartnerAuthService:
    return PartnerAuthService(
        repository=PartnersRepository(),
        audit_service=AuditService(AuditRepository()),
        notifications_service=get_notifications_service(),
    )
