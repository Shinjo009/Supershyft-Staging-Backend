"""Bio-AI report + trends read stored individual_health_report.reports, not MetSights."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from core.exceptions import AppError
from modules.bioai_report.report_engine.builders.patient_builder import build_patient
from modules.bioai_report.report_engine.knowledge_base.loader import KnowledgeBaseStore
from modules.bioai_report.report_engine.models.assessment import AssessmentPayload
from modules.bioai_report.report_engine.models.trends import TREND_DISEASE_TITLES
from modules.bioai_report.report_engine.services.patient_service import PatientProfileService
from modules.bioai_report.report_engine.services.report_service import BioReportService
from modules.bioai_report.report_engine.services.trend_service import BioAITrendService
from tests.modules.bioai_report.test_bioai_trends import (
    _FakeAssessments,
    _FakeFetch,
    _FakeReports,
    _FakeUsers,
    _instance,
    _package,
    _payload,
    _reports_from_payload,
)


class _FakeReportAssessments:
    def __init__(self, instances: list) -> None:
        self.instances = {int(row.assessment_instance_id): row for row in instances}

    async def get_instance_by_id(self, db, assessment_instance_id: int):
        return self.instances.get(int(assessment_instance_id))


class _FakeIHRRepo:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    async def list_completed_bioai_reports_for_user(self, db, *, user_id: int):
        by_id: dict[int, tuple] = {}
        for instance, package, ihr in self.rows:
            if str(getattr(instance, "status", "completed")).lower() != "completed":
                continue
            key = int(instance.assessment_instance_id)
            report_id = int(getattr(ihr, "report_id", 0) or 0)
            previous = by_id.get(key)
            previous_id = int(getattr(previous[2], "report_id", 0) or 0) if previous else -1
            if previous is None or report_id >= previous_id:
                by_id[key] = (instance, package, ihr)
        return list(by_id.values())

    async def get_individual_report_by_assessment(self, db, *, assessment_instance_id: int):
        matching = [
            row
            for row in self.rows
            if int(row[0].assessment_instance_id) == int(assessment_instance_id)
        ]
        if not matching:
            return None
        return max(matching, key=lambda row: int(getattr(row[2], "report_id", 0) or 0))[2]


class _ExplodingFetch:
    async def fetch_raw(self, *, record_id: str, assessment_type_code: str | None = None):
        raise AssertionError("MetSights must not be called for stored Bio-AI reports")

    async def fetch(self, *, record_id: str, assessment_type_code: str | None = None):
        raise AssertionError("MetSights must not be called for stored Bio-AI reports")


class _ExplodingMetsights:
    def __getattr__(self, name):
        async def _explode(*args, **kwargs):
            raise AssertionError(f"MetSights method {name} must not be called")

        return _explode


class _ProfileUsers:
    def __init__(self, user) -> None:
        self.user = user

    async def get_user_by_id(self, db, user_id: int):
        return self.user if int(self.user.user_id) == int(user_id) else None


class _NoQuestionnaire:
    async def list_responses_for_instance(self, db, *, assessment_instance_id: int):
        return []

    async def get_definitions_by_ids(self, db, *, question_ids: list[int]):
        return {}


def _patient_service(user) -> PatientProfileService:
    return PatientProfileService(
        _ExplodingMetsights(),
        users_repository=_ProfileUsers(user),
        questionnaire_repository=_NoQuestionnaire(),
    )


def _ihr(reports: dict, *, report_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(reports=reports, report_id=report_id)


def _reports(*, date: str, diseases: list[tuple[str, int]], metabolic_score: int | None = None) -> dict:
    return _reports_from_payload(
        _payload(date=date, diseases=diseases, metabolic_score=metabolic_score)
    )


def _empty_series() -> dict:
    return {
        "series": [
            {"disease_id": disease_id, "title": title, "points": []}
            for disease_id, title in TREND_DISEASE_TITLES.items()
        ]
    }


def test_patient_height_is_rounded_to_one_decimal():
    assert build_patient(AssessmentPayload(height=5.833333333333333)).height == 5.8
    assert build_patient(AssessmentPayload(height=167)).height == 167.0


@pytest.mark.asyncio
async def test_single_assessment_report_has_empty_trend_points():
    instance = _instance(instance_id=1, record_id="r1", completed="2024-01-01")
    instance.status = "completed"
    instance.user_id = 7
    user = SimpleNamespace(
        user_id=7,
        first_name="Ada",
        last_name="Ng",
        age=41,
        date_of_birth=None,
        gender="female",
        metsights_profile_id=None,
    )
    rows = [
        (
            instance,
            _package(),
            _ihr(_reports(date="2024-01-01", diseases=[("hypertension", 40)])),
        )
    ]
    report = await BioReportService(
        assessment_service=_ExplodingFetch(),
        patient_service=_patient_service(user),
        kb_store=KnowledgeBaseStore(),
        assessments_repository=_FakeReportAssessments([instance]),
        reports_repository=_FakeIHRRepo(rows),
    ).generate_for_assessment_instance(assessment_instance_id=1, db=None)
    body = report.to_dict()
    assert set(body) >= {"patient", "executive_summary", "disease_sections", "report_metadata"}
    assert body["patient"]["user_id"] == 7
    assert body["executive_summary"]["patient"]["user_id"] == 7

    trends = BioAITrendService(
        assessment_service=_ExplodingFetch(),
        assessments_repository=_FakeAssessments([(instance, _package())]),
        users_repository=_FakeUsers(gender="female"),
        reports_repository=_FakeReports([(instance, _package())], {
            "r1": _payload(date="2024-01-01", diseases=[("hypertension", 40)]),
        }),
    )
    embedded = await trends.embed_for_assessment_instance(
        None,
        assessment_instance_id=1,
        report_payload=body,
    )
    assert embedded == _empty_series()


@pytest.mark.asyncio
async def test_two_assessments_request_second_includes_first_and_second():
    one = _instance(instance_id=1, record_id="r1", completed="2024-01-01")
    two = _instance(instance_id=2, record_id="r2", completed="2025-01-01")
    rows = [(one, _package()), (two, _package())]
    payloads = {
        "r1": _payload(date="2024-01-01", diseases=[("hypertension", 40)]),
        "r2": _payload(date="2025-01-01", diseases=[("hypertension", 32)]),
    }
    embedded = await BioAITrendService(
        assessment_service=_ExplodingFetch(),
        assessments_repository=_FakeAssessments(rows),
        users_repository=_FakeUsers(gender="female"),
        reports_repository=_FakeReports(rows, payloads),
    ).embed_for_assessment_instance(
        None,
        assessment_instance_id=2,
        report_payload={"patient": {"assessment_date": "2025-01-01", "sex": "female"}},
    )
    by_id = {item["disease_id"]: item for item in embedded["series"]}
    assert [p["score"] for p in by_id["hypertension"]["points"]] == [40, 32]


@pytest.mark.asyncio
async def test_three_assessments_request_second_excludes_third():
    rows = [
        (_instance(instance_id=1, record_id="r1", completed="2024-01-01"), _package()),
        (_instance(instance_id=2, record_id="r2", completed="2025-01-01"), _package()),
        (_instance(instance_id=3, record_id="r3", completed="2026-01-01"), _package()),
    ]
    payloads = {
        "r1": _payload(date="2024-01-01", diseases=[("nafld", 10)]),
        "r2": _payload(date="2025-01-01", diseases=[("nafld", 12)]),
        "r3": _payload(date="2026-01-01", diseases=[("nafld", 14)]),
    }
    fetch = _FakeFetch(payloads)
    trends = BioAITrendService(
        assessment_service=fetch,
        assessments_repository=_FakeAssessments(rows),
        users_repository=_FakeUsers(gender="female"),
        reports_repository=_FakeReports(rows, payloads),
    )
    second = await trends.embed_for_assessment_instance(
        None,
        assessment_instance_id=2,
        report_payload={"patient": {"assessment_date": "2025-01-01"}},
    )
    third = await trends.embed_for_assessment_instance(
        None,
        assessment_instance_id=3,
        report_payload={"patient": {"assessment_date": "2026-01-01"}},
    )
    assert fetch.fetch_calls == 0
    by_second = {item["disease_id"]: item for item in second["series"]}
    by_third = {item["disease_id"]: item for item in third["series"]}
    assert [p["score"] for p in by_second["nafld"]["points"]] == [10, 12]
    assert [p["score"] for p in by_third["nafld"]["points"]] == [10, 12, 14]


@pytest.mark.asyncio
async def test_latest_completed_stored_reports_used_for_bioai_not_highest_id():
    older = _instance(instance_id=101, record_id="old", completed="2025-01-01")
    newer_lower_id = _instance(instance_id=100, record_id="new", completed="2026-06-01")
    older.status = newer_lower_id.status = "completed"
    older.user_id = newer_lower_id.user_id = 7
    rows = [
        (older, _package(), _ihr(_reports(date="2025-01-01", diseases=[("obesity", 20)]))),
        (newer_lower_id, _package(), _ihr(_reports(date="2026-06-01", diseases=[("obesity", 70)]))),
    ]
    svc = BioReportService(
        assessment_service=_ExplodingFetch(),
        patient_service=None,
        kb_store=KnowledgeBaseStore(),
        assessments_repository=_FakeReportAssessments([older, newer_lower_id]),
        reports_repository=_FakeIHRRepo(rows),
    )
    report = await svc.generate_for_assessment_instance(assessment_instance_id=101, db=None)
    body = report.to_dict()
    obesity = next(section for section in body["disease_sections"] if section["disease_id"] == "obesity")
    assert obesity["current_status"]["score"] == 70
    assert set(body) >= {"patient", "executive_summary", "disease_sections", "report_metadata"}


@pytest.mark.asyncio
async def test_active_instance_uses_own_stored_reports_when_present():
    active = _instance(instance_id=55, record_id="r55", completed="2026-08-01")
    active.status = "active"
    active.user_id = 12
    rows = [
        (active, _package(), _ihr(_reports(date="2026-08-01", diseases=[("obesity", 44)]))),
    ]
    svc = BioReportService(
        assessment_service=_ExplodingFetch(),
        patient_service=None,
        kb_store=KnowledgeBaseStore(),
        assessments_repository=_FakeReportAssessments([active]),
        reports_repository=_FakeIHRRepo(rows),
    )
    report = await svc.generate_for_assessment_instance(assessment_instance_id=55, db=None)
    obesity = next(
        section
        for section in report.to_dict()["disease_sections"]
        if section["disease_id"] == "obesity"
    )
    assert obesity["current_status"]["score"] == 44


@pytest.mark.asyncio
async def test_requested_active_instance_without_ihr_uses_latest_qualifying():
    requested = _instance(instance_id=99, record_id="", completed="2026-07-01")
    requested.status = "active"
    requested.completed_at = None
    requested.user_id = 7
    completed = _instance(instance_id=10, record_id="", completed="2026-06-01")
    completed.status = "completed"
    completed.user_id = 7
    rows = [
        (
            completed,
            _package(),
            _ihr(_reports(date="2026-06-01", diseases=[("obesity", 63)])),
        )
    ]
    user = SimpleNamespace(
        user_id=7,
        first_name="Correct",
        last_name="User",
        age=29,
        date_of_birth=None,
        gender="female",
        metsights_profile_id=None,
    )
    svc = BioReportService(
        assessment_service=_ExplodingFetch(),
        patient_service=_patient_service(user),
        kb_store=KnowledgeBaseStore(),
        assessments_repository=_FakeReportAssessments([requested, completed]),
        reports_repository=_FakeIHRRepo(rows),
    )
    report = await svc.generate_for_assessment_instance(assessment_instance_id=99, db=None)
    obesity = next(
        section
        for section in report.to_dict()["disease_sections"]
        if section["disease_id"] == "obesity"
    )
    assert obesity["current_status"]["score"] == 63


@pytest.mark.asyncio
async def test_missing_stored_reports_raises_ihr_not_available():
    instance = _instance(instance_id=5, record_id="r5", completed="2026-01-01")
    instance.user_id = 9
    svc = BioReportService(
        assessment_service=_ExplodingFetch(),
        assessments_repository=_FakeReportAssessments([instance]),
        reports_repository=_FakeIHRRepo([]),
    )
    with pytest.raises(ValueError, match="IHR not available"):
        await svc.generate_for_assessment_instance(assessment_instance_id=5, db=None)


@pytest.mark.asyncio
async def test_missing_assessment_raises_assessment_not_found():
    svc = BioReportService(
        assessment_service=_ExplodingFetch(),
        assessments_repository=_FakeReportAssessments([]),
        reports_repository=_FakeIHRRepo([]),
    )
    with pytest.raises(AppError) as exc:
        await svc.generate_for_assessment_instance(assessment_instance_id=11216, db=None)
    assert exc.value.status_code == 404
    assert exc.value.error_code == "ASSESSMENT_NOT_FOUND"
    assert exc.value.message == "Assessment does not exist"


@pytest.mark.asyncio
async def test_patient_uses_authoritative_local_user_demographics():
    requested = _instance(instance_id=50, record_id="", completed="2026-01-01")
    requested.status = "completed"
    requested.user_id = 700
    stored = _reports(date="2026-01-01", diseases=[("obesity", 42)])
    stored.update(
        {
            "name": "Stale IHR Name",
            "age": 99,
            "gender": "male",
            "date_of_birth": "1900-01-01",
        }
    )
    user = SimpleNamespace(
        user_id=700,
        first_name="Asha",
        last_name="Rao",
        age=36,
        date_of_birth=date(1990, 4, 12),
        gender="female",
        metsights_profile_id="profile-700",
    )
    svc = BioReportService(
        assessment_service=_ExplodingFetch(),
        patient_service=_patient_service(user),
        kb_store=KnowledgeBaseStore(),
        assessments_repository=_FakeReportAssessments([requested]),
        reports_repository=_FakeIHRRepo([(requested, _package(), _ihr(stored))]),
    )
    body = (await svc.generate_for_assessment_instance(assessment_instance_id=50, db=None)).to_dict()
    for block in (body["patient"], body["executive_summary"]["patient"]):
        assert block["user_id"] == 700
        assert block["name"] == "Asha Rao"
        assert block["age"] == 36
        assert block["gender"] == "female"
        assert block["sex"] == "female"
        assert block["date_of_birth"] == "1990-04-12"
        assert block["profile_id"] == "profile-700"


@pytest.mark.asyncio
async def test_patient_age_is_calculated_from_dob_when_stored_age_is_missing():
    requested = _instance(instance_id=51, record_id="", completed="2026-01-01")
    requested.status = "completed"
    requested.user_id = 701
    dob = date(2000, 12, 31)
    today = date.today()
    expected_age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    user = SimpleNamespace(
        user_id=701,
        first_name="Dev",
        last_name=None,
        age=None,
        date_of_birth=dob,
        gender=None,
        metsights_profile_id=None,
    )
    svc = BioReportService(
        assessment_service=_ExplodingFetch(),
        patient_service=_patient_service(user),
        kb_store=KnowledgeBaseStore(),
        assessments_repository=_FakeReportAssessments([requested]),
        reports_repository=_FakeIHRRepo(
            [(requested, _package(), _ihr(_reports(date="2026-01-01", diseases=[("nafld", 30)])))]
        ),
    )
    patient = (
        await svc.generate_for_assessment_instance(assessment_instance_id=51, db=None)
    ).to_dict()["patient"]
    assert patient["age"] == expected_age
    assert patient["date_of_birth"] == "2000-12-31"
    assert patient["gender"] is None
    assert patient["sex"] is None


@pytest.mark.asyncio
async def test_optional_demographic_null_does_not_crash_report():
    requested = _instance(instance_id=52, record_id="", completed="2026-01-01")
    requested.status = "completed"
    requested.user_id = 702
    user = SimpleNamespace(
        user_id=702,
        first_name=None,
        last_name=None,
        age=None,
        date_of_birth=None,
        gender=None,
        metsights_profile_id=None,
    )
    report = await BioReportService(
        assessment_service=_ExplodingFetch(),
        patient_service=_patient_service(user),
        kb_store=KnowledgeBaseStore(),
        assessments_repository=_FakeReportAssessments([requested]),
        reports_repository=_FakeIHRRepo(
            [(requested, _package(), _ihr(_reports(date="2026-01-01", diseases=[("obesity", 11)])))]
        ),
    ).generate_for_assessment_instance(assessment_instance_id=52, db=None)
    patient = report.to_dict()["patient"]
    assert patient["user_id"] == 702
    assert patient["name"] is None
    assert patient["age"] is None
    assert patient["date_of_birth"] is None


@pytest.mark.asyncio
async def test_duplicate_ihr_uses_latest_report_id_once():
    instance = _instance(instance_id=10, record_id="dup", completed="2026-01-01")
    instance.status = "completed"
    instance.user_id = 8
    older = _ihr(_reports(date="2026-01-01", diseases=[("obesity", 10)]), report_id=1)
    newer = _ihr(_reports(date="2026-01-01", diseases=[("obesity", 70)]), report_id=9)
    rows = [(instance, _package(), older), (instance, _package(), newer)]
    report = await BioReportService(
        assessment_service=_ExplodingFetch(),
        patient_service=None,
        kb_store=KnowledgeBaseStore(),
        assessments_repository=_FakeReportAssessments([instance]),
        reports_repository=_FakeIHRRepo(rows),
    ).generate_for_assessment_instance(assessment_instance_id=10, db=None)
    obesity = next(
        section
        for section in report.to_dict()["disease_sections"]
        if section["disease_id"] == "obesity"
    )
    assert obesity["current_status"]["score"] == 70

    trends = await BioAITrendService(
        assessments_repository=_FakeAssessments([(instance, _package())]),
        users_repository=_FakeUsers(),
        reports_repository=_FakeIHRRepo(rows),
    ).get_trends_for_user(None, user_id=8)
    assert trends.assessment_count == 1
    assert [p.score for p in trends.trends.obesity] == [70]
