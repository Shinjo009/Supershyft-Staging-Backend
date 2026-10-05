"""HTTP client for Metsights APIs."""

from __future__ import annotations

import re
from typing import Any

import httpx

from core.config import settings

_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _metsights_url(path: str) -> str:
    """Build MetSights URL with trailing slash. External API paths use ``/external/`` prefix."""
    base_url = settings.METSIGHTS_BASE_URL.rstrip("/")
    suffix = (path or "").strip().strip("/")
    if suffix.startswith("engagements/"):
        return f"{base_url}/{suffix}/"
    if suffix.startswith("external/"):
        return f"{base_url}/{suffix}/"
    return f"{base_url}/external/{suffix}/"


_ALLOWED_RESOURCES = frozenset({
    "advanced-blood-parameters",
    "blood-parameters",
    "diet-lifestyle-parameters",
    "fitness-parameters",
    "physical-measurement",
    "anthropometrics",
    "assessments",
    "blood-biomarkers",
    "blood-pressure",
    "body-composition",
    "cardiac-health",
    "cardio-metabolic-risk",
    "clinical-chemistry",
    "complete-blood-count",
    "diabetes",
    "diet-plan",
    "endocrinology",
    "exercise-plan",
    "fetch-collections",
    "fitness-assessment",
    "glucose-tolerance",
    "haematology",
    "health-risk",
    "hematology",
    "hepatic",
    "immunology",
    "kidney",
    "lifestyle",
    "lipid-profile",
    "liver-function",
    "metabolic-health",
    "musculo-skeletal",
    "nutrition",
    "obesity",
    "overall-health",
    "physical-activity",
    "pulmonary-function",
    "questionnaire",
    "renal-function",
    "serology",
    "sleep",
    "stress",
    "thyroid",
    "thyroid-function",
    "urinalysis",
    "vitals",
    "well-being",
})


def _validate_record_id(record_id: str) -> str:
    rid = (record_id or "").strip().strip("/")
    if not rid or not _SAFE_ID_PATTERN.match(rid):
        raise ValueError(f"Invalid record_id: {record_id!r}")
    return rid


def _validate_resource(resource: str) -> str:
    res = (resource or "").strip().strip("/")
    if not res or not _SAFE_ID_PATTERN.match(res):
        raise ValueError(f"Invalid resource: {resource!r}")
    return res


class MetsightsClient:
    """Thin HTTP client for Metsights resources."""

    async def get_profile_detail(self, *, profile_id: str) -> dict[str, Any]:
        pid = _validate_record_id(profile_id)
        url = _metsights_url(f"profiles/{pid}")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def get_record_resource(self, *, record_id: str, resource: str) -> dict[str, Any]:
        rid = _validate_record_id(record_id)
        res = _validate_resource(resource)
        url = _metsights_url(f"records/{rid}/{res}")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def options_record_resource(self, *, record_id: str, resource: str) -> dict[str, Any]:
        rid = _validate_record_id(record_id)
        res = _validate_resource(resource)
        url = _metsights_url(f"records/{rid}/{res}")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request("OPTIONS", url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def get_report(self, *, record_id: str, assessment_type_code: str | None) -> dict[str, Any]:
        rid = _validate_record_id(record_id)
        type_code = (assessment_type_code or "").strip()
        if type_code == "7":
            url = _metsights_url(f"reports/fitness/{rid}")
        else:
            url = _metsights_url(f"reports/metsights/{rid}")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def get_report_pdf(self, *, record_id: str, assessment_type_code: str | None) -> dict[str, Any]:
        rid = _validate_record_id(record_id)
        type_code = (assessment_type_code or "").strip()
        if type_code == "7":
            url = _metsights_url(f"reports/fitness/{rid}/pdf")
        else:
            url = _metsights_url(f"reports/metsights/{rid}/pdf")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def get_record_fetch_collections(self, *, record_id: str) -> dict[str, Any]:
        """GET /records/{record_id}/fetch-collections/ — sample collection details."""
        return await self.get_record_resource(record_id=record_id, resource="fetch-collections")

    async def create_profile(self, *, data: dict[str, Any]) -> dict[str, Any]:
        url = _metsights_url("profiles")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def create_profile_for_engagement(self, *, engagement_id: str, data: dict[str, Any]) -> dict[str, Any]:
        eid = str(engagement_id or "").strip()
        if not eid:
            raise ValueError("engagement_id is required")
        url = _metsights_url(f"engagements/{eid}/register")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def list_profiles(
        self,
        *,
        search: str | None = None,
        page: int | None = None,
        next_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = timeout_seconds if timeout_seconds is not None else settings.METSIGHTS_TIMEOUT_SECONDS

        if next_url is not None and str(next_url).strip() != "":
            url = str(next_url).strip()
            params: dict[str, Any] | None = None
        else:
            url = _metsights_url("profiles")
            params = {}
            if search is not None and str(search).strip() != "":
                params["search"] = str(search).strip()
            if page is not None and page > 0:
                params["page"] = page

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": []}
            return payload

    async def create_profile_record(self, *, profile_id: str, data: dict[str, Any]) -> dict[str, Any]:
        pid = _validate_record_id(profile_id)
        url = _metsights_url(f"profiles/{pid}/records")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def list_profile_records(
        self,
        *,
        profile_id: str,
        completed: str | None = None,
        code: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        pid = _validate_record_id(profile_id)
        url = _metsights_url(f"profiles/{pid}/records")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS
        params: dict[str, Any] = {}
        if completed is not None and str(completed).strip() != "":
            params["completed"] = str(completed).strip()
        if code is not None and str(code).strip() != "":
            params["code"] = str(code).strip()
        if search is not None and str(search).strip() != "":
            params["search"] = str(search).strip()

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers, params=params or None)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def patch_record_resource(self, *, record_id: str, resource: str, data: dict[str, Any]) -> dict[str, Any]:
        rid = _validate_record_id(record_id)
        res = _validate_resource(resource)
        url = _metsights_url(f"records/{rid}/{res}")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.patch(url, headers=headers, json=data)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def post_record_resource(self, *, record_id: str, resource: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST creates a sub-resource (first questionnaire submission per Metsights Records API)."""

        rid = _validate_record_id(record_id)
        res = _validate_resource(resource)
        url = _metsights_url(f"records/{rid}/{res}")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload

    async def get_record_detail(self, *, record_id: str) -> dict[str, Any]:
        rid = _validate_record_id(record_id)
        url = _metsights_url(f"records/{rid}")
        headers = {"X-API-KEY": settings.METSIGHTS_API_KEY}
        timeout = settings.METSIGHTS_TIMEOUT_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {"detail": "Unexpected response", "data": None}
            return payload
