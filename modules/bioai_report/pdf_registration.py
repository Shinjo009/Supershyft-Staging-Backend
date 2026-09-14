"""Register permanent Bio-AI PDF links via the bio-ai-reports service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.exceptions import AppError
from modules.audit.cron_sync_logging import tracked_integration_call
from modules.audit.models import IntegrationSyncLog
from modules.bioai_report.client import BioAiReportsClient
from modules.bioai_report.report_engine.services.report_service import BioReportService
from modules.reports.repository import ReportsRepository

_PROVIDER = "bio_ai_reports"
_BIO_AI_TYPE_CODES = frozenset({"1", "2"})


def is_bio_ai_assessment_type(assessment_type_code: str | None) -> bool:
    return (assessment_type_code or "").strip() in _BIO_AI_TYPE_CODES


def bioreport_generate_endpoint(assessment_instance_id: int) -> str:
    return f"internal://bioai-report/{assessment_instance_id}"


def bioreport_register_endpoint() -> str:
    base = (settings.BIO_AI_REPORTS_BASE_URL or "").strip().rstrip("/")
    return f"{base}/api/reports"


def bioreport_regenerate_endpoint() -> str:
    base = (settings.BIO_AI_REPORTS_BASE_URL or "").strip().rstrip("/")
    return f"{base}/api/reports/regenerate"


def extract_slug_from_report_url(url: str | None) -> str | None:
    """Parse the public slug from a bio-ai-reports permanent URL."""
    cleaned = (url or "").strip()
    if not cleaned or "/r/" not in cleaned:
        return None
    slug = cleaned.split("/r/", 1)[1]
    slug = slug.split("?", 1)[0].split("#", 1)[0].strip().rstrip("/")
    return slug or None


def is_bio_ai_reports_permanent_url(url: str | None) -> bool:
    return extract_slug_from_report_url(url) is not None


def _url_from_register_response_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    url = payload.get("url")
    if isinstance(url, str) and is_bio_ai_reports_permanent_url(url):
        return url.strip()
    slug = payload.get("slug")
    if isinstance(slug, str) and slug.strip():
        base = (settings.BIO_AI_REPORTS_BASE_URL or "").strip().rstrip("/")
        if base:
            return f"{base}/r/{slug.strip()}"
    return None


async def lookup_first_registered_bio_ai_report_url(
    db: AsyncSession,
    *,
    user_id: int,
    engagement_id: int,
) -> str | None:
    """Return the earliest successful bio-ai-reports register URL for this participant."""
    register_endpoint = bioreport_register_endpoint()
    result = await db.execute(
        select(IntegrationSyncLog.response_payload)
        .where(IntegrationSyncLog.provider == _PROVIDER)
        .where(IntegrationSyncLog.user_id == user_id)
        .where(IntegrationSyncLog.engagement_id == engagement_id)
        .where(IntegrationSyncLog.status == "success")
        .where(IntegrationSyncLog.api_endpoint_url == register_endpoint)
        .order_by(
            IntegrationSyncLog.created_at.asc(),
            IntegrationSyncLog.sync_log_id.asc(),
        )
        .limit(1)
    )
    payload = result.scalar_one_or_none()
    return _url_from_register_response_payload(payload)


async def lookup_existing_bio_ai_report_url(
    db: AsyncSession,
    *,
    user_id: int | None,
    engagement_id: int | None,
    assessment_instance_id: int,
) -> str | None:
    """Return a cached permanent bio-ai-reports URL without creating a new slug."""
    if user_id is not None and engagement_id is not None:
        first_registered = await lookup_first_registered_bio_ai_report_url(
            db,
            user_id=user_id,
            engagement_id=engagement_id,
        )
        if first_registered:
            return first_registered

    repo = ReportsRepository()
    assessment_report = await repo.get_individual_report_by_assessment(
        db,
        assessment_instance_id=assessment_instance_id,
    )
    if assessment_report is not None:
        cached = (assessment_report.report_url or "").strip()
        if is_bio_ai_reports_permanent_url(cached):
            return cached

    if user_id is not None and engagement_id is not None:
        engagement_report = await repo.get_individual_report_by_engagement(
            db,
            user_id=user_id,
            engagement_id=engagement_id,
        )
        if engagement_report is not None:
            cached = (engagement_report.report_url or "").strip()
            if is_bio_ai_reports_permanent_url(cached):
                return cached

    return None


async def resolve_canonical_bio_ai_report_url(
    db: AsyncSession,
    *,
    user_id: int,
    engagement_id: int,
    assessment_instance_id: int,
    report_url: str | None,
) -> str | None:
    """Prefer the first registered slug (emailed link) over later overwritten URLs."""
    existing = await lookup_existing_bio_ai_report_url(
        db,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_instance_id=assessment_instance_id,
    )
    if existing:
        return existing

    current = (report_url or "").strip()
    if is_bio_ai_reports_permanent_url(current):
        return current
    return None


def summarize_bioreport_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("report_metadata") if isinstance(payload.get("report_metadata"), dict) else {}
    patient = payload.get("patient") if isinstance(payload.get("patient"), dict) else {}
    return {
        "record_id": metadata.get("record_id"),
        "patient_name": patient.get("name"),
        "disease_count": metadata.get("disease_count"),
        "engine_version": metadata.get("engine_version"),
        "truncated": True,
    }


def extract_registered_report_url(response: dict[str, Any]) -> str:
    url = response.get("url")
    if not isinstance(url, str) or not url.strip():
        raise AppError(
            status_code=502,
            error_code="BIO_AI_REPORTS_ERROR",
            message="bio-ai-reports did not return a report url",
        )
    return url.strip()


async def register_permanent_bio_ai_report_url(
    db: AsyncSession,
    *,
    assessment_instance_id: int,
    engagement_id: int | None = None,
    user_id: int | None = None,
    bio_report_service: BioReportService | None = None,
    bio_ai_reports_client: BioAiReportsClient | None = None,
) -> str:
    """Generate BioReport JSON and register a permanent PDF link."""
    service = bio_report_service
    if service is None:
        from modules.bioai_report.report_engine.api.dependencies import get_bioreport_service

        service = get_bioreport_service()
    client = bio_ai_reports_client or BioAiReportsClient()
    instance_id = int(assessment_instance_id)

    existing_url = await lookup_existing_bio_ai_report_url(
        db,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_instance_id=instance_id,
    )
    if existing_url:
        return existing_url

    bioreport_payload = await tracked_integration_call(
        db,
        provider=_PROVIDER,
        api_url=bioreport_generate_endpoint(instance_id),
        engagement_id=engagement_id,
        user_id=user_id,
        request_payload={"assessment_instance_id": instance_id},
        operation=lambda: _generate_bioreport_payload(
            service,
            assessment_instance_id=instance_id,
            db=db,
        ),
        reraise=True,
    )
    if not isinstance(bioreport_payload, dict):
        raise AppError(
            status_code=500,
            error_code="INTERNAL_ERROR",
            message="BioReport generation returned an invalid payload",
        )

    registration_response = await tracked_integration_call(
        db,
        provider=_PROVIDER,
        api_url=bioreport_register_endpoint(),
        engagement_id=engagement_id,
        user_id=user_id,
        request_payload=summarize_bioreport_payload(bioreport_payload),
        operation=lambda: client.register_report(bioreport_payload),
        reraise=True,
    )
    if not isinstance(registration_response, dict):
        raise AppError(
            status_code=502,
            error_code="BIO_AI_REPORTS_ERROR",
            message="bio-ai-reports returned an invalid response",
        )
    return extract_registered_report_url(registration_response)


async def regenerate_permanent_bio_ai_report_url(
    db: AsyncSession,
    *,
    assessment_instance_id: int,
    report_url: str,
    engagement_id: int | None = None,
    user_id: int | None = None,
    bio_report_service: BioReportService | None = None,
    bio_ai_reports_client: BioAiReportsClient | None = None,
) -> str:
    """Regenerate BioReport JSON and overwrite the PDF at an existing permanent slug."""
    slug = extract_slug_from_report_url(report_url)
    if not slug:
        raise AppError(
            status_code=400,
            error_code="VALIDATION_ERROR",
            message="report_url does not contain a bio-ai-reports slug",
        )

    service = bio_report_service
    if service is None:
        from modules.bioai_report.report_engine.api.dependencies import get_bioreport_service

        service = get_bioreport_service()
    client = bio_ai_reports_client or BioAiReportsClient()
    instance_id = int(assessment_instance_id)
    existing_url = report_url.strip()

    bioreport_payload = await tracked_integration_call(
        db,
        provider=_PROVIDER,
        api_url=bioreport_generate_endpoint(instance_id),
        engagement_id=engagement_id,
        user_id=user_id,
        request_payload={"assessment_instance_id": instance_id, "slug": slug},
        operation=lambda: _generate_bioreport_payload(
            service,
            assessment_instance_id=instance_id,
            db=db,
        ),
        reraise=True,
    )
    if not isinstance(bioreport_payload, dict):
        raise AppError(
            status_code=500,
            error_code="INTERNAL_ERROR",
            message="BioReport generation returned an invalid payload",
        )

    registration_response = await tracked_integration_call(
        db,
        provider=_PROVIDER,
        api_url=bioreport_regenerate_endpoint(),
        engagement_id=engagement_id,
        user_id=user_id,
        request_payload={
            **summarize_bioreport_payload(bioreport_payload),
            "slug": slug,
        },
        operation=lambda: client.regenerate_report(bioreport_payload, slug=slug),
        reraise=True,
    )
    if not isinstance(registration_response, dict):
        raise AppError(
            status_code=502,
            error_code="BIO_AI_REPORTS_ERROR",
            message="bio-ai-reports returned an invalid response",
        )

    regenerated_url = extract_registered_report_url(registration_response)
    if regenerated_url.rstrip("/") != existing_url.rstrip("/"):
        raise AppError(
            status_code=502,
            error_code="BIO_AI_REPORTS_ERROR",
            message="bio-ai-reports regenerate returned a different report url",
        )
    return existing_url


async def _generate_bioreport_payload(
    service: BioReportService,
    *,
    assessment_instance_id: int,
    db: AsyncSession,
) -> dict[str, Any]:
    report = await service.generate_for_assessment_instance(
        assessment_instance_id=assessment_instance_id,
        db=db,
    )
    return report.to_dict()
