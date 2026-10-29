"""Engagements module dependencies."""

from __future__ import annotations

from modules.assessments.dependencies import get_assessments_service
from modules.assessments.repository import AssessmentsRepository
from modules.audit.repository import AuditRepository
from modules.audit.service import AuditService
from modules.engagements.assessment_packages_service import (
    EngagementAssessmentPackagesService,
)
from modules.engagements.console.service import ConsoleService
from modules.engagements.onboarding_assistants_service import OnboardingAssistantsService
from modules.engagement_types.repository import EngagementTypesRepository
from modules.engagements.engagement_feedback_repository import EngagementFeedbackRepository
from modules.engagements.engagement_feedback_service import EngagementFeedbackService
from modules.engagements.repository import EngagementsRepository
from modules.engagements.service import EngagementsService
from modules.experts.dependencies import get_expert_types_service
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService
from modules.notifications.dependencies import get_notifications_service
from modules.notifications.repository import NotificationsRepository
from modules.organizations.repository import OrganizationsRepository
from modules.questionnaire.repository import QuestionnaireRepository
from modules.reports.repository import ReportsRepository
from modules.users.repository import UsersRepository
from modules.audit.repository import AuditRepository
from modules.audit.service import AuditService
from modules.engagements.onboarding_payload_repository import (
    CampOnboardingPayloadRepository,
    UserOnboardingPayloadFieldsRepository,
)
from modules.engagements.onboarding_payload_service import (
    CampOnboardingPayloadService,
    UserOnboardingPayloadFieldsService,
)
from modules.experts.repository import ExpertTypesRepository


def get_user_onboarding_payload_fields_service() -> UserOnboardingPayloadFieldsService:
    return UserOnboardingPayloadFieldsService(
        repository=UserOnboardingPayloadFieldsRepository(),
        audit_service=AuditService(AuditRepository()),
    )


def get_camp_onboarding_payload_service() -> CampOnboardingPayloadService:
    return CampOnboardingPayloadService(
        camp_repository=CampOnboardingPayloadRepository(),
        fields_repository=UserOnboardingPayloadFieldsRepository(),
        expert_types_repository=ExpertTypesRepository(),
        audit_service=AuditService(AuditRepository()),
    )


def get_engagements_repository() -> EngagementsRepository:
    return EngagementsRepository()


def get_engagement_feedback_service() -> EngagementFeedbackService:
    return EngagementFeedbackService(
        feedback_repository=EngagementFeedbackRepository(),
        engagements_repository=EngagementsRepository(),
        engagement_types_repository=EngagementTypesRepository(),
    )


def get_engagements_service() -> EngagementsService:
    audit_service = AuditService(AuditRepository())
    organizations_repository = OrganizationsRepository()
    return EngagementsService(
        repository=EngagementsRepository(),
        audit_service=audit_service,
        organizations_repository=organizations_repository,
        users_repository=UsersRepository(),
        assessments_service=get_assessments_service(),
        metsights_service=MetsightsService(client=MetsightsClient()),
        notifications_repository=NotificationsRepository(),
        notifications_service=get_notifications_service(),
        expert_types_service=get_expert_types_service(),
        camp_onboarding_payload_service=get_camp_onboarding_payload_service(),
    )


def get_onboarding_assistants_service() -> OnboardingAssistantsService:
    from modules.employee.repository import EmployeeRepository
    from modules.partners.dependencies import get_partners_service
    from modules.partners.repository import PartnersRepository

    audit_service = AuditService(AuditRepository())
    return OnboardingAssistantsService(
        repository=EngagementsRepository(),
        partners_repository=PartnersRepository(),
        employee_repository=EmployeeRepository(),
        partners_service=get_partners_service(),
        audit_service=audit_service,
    )


def get_console_service() -> ConsoleService:
    from modules.assessments.dependencies import get_assessment_package_categories_service
    from modules.metsights.dependencies import get_metsights_sync_service
    from modules.questionnaire.dependencies import get_questionnaire_user_service

    return ConsoleService(
        repository=EngagementsRepository(),
        users_repository=UsersRepository(),
        assessments_repository=AssessmentsRepository(),
        assessments_service=get_assessments_service(),
        categories_service=get_assessment_package_categories_service(),
        questionnaire_service=get_questionnaire_user_service(),
        metsights_sync_service=get_metsights_sync_service(),
    )


def get_engagement_assessment_packages_service() -> EngagementAssessmentPackagesService:
    return EngagementAssessmentPackagesService(
        engagements_repository=EngagementsRepository(),
        assessments_repository=AssessmentsRepository(),
        reports_repository=ReportsRepository(),
        questionnaire_repository=QuestionnaireRepository(),
        users_repository=UsersRepository(),
        assessments_service=get_assessments_service(),
        metsights_service=MetsightsService(client=MetsightsClient()),
        audit_service=AuditService(AuditRepository()),
    )
