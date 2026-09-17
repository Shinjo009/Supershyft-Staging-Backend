"""Section-aware assembly: enrich Camp Report JSON with intelligence in place.

Keeps ``generate_report_insights`` generation logic unchanged. Only maps its
output onto existing camp-report section objects under an ``intelligence`` key.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Mapping, MutableMapping, Optional

from .engine import generate_report_insights, generate_section_insights

# Camp section keys that may receive an ``intelligence`` field (engine-backed).
INTELLIGENCE_CAMP_SECTIONS: frozenset[str] = frozenset(
    {
        "overall_risk_score",
        "distribution_by_physical_activity_frequency",
        "distribution_by_sleeping_hours",
        "distribution_by_oxidative_stress",
        "distribution_by_gender_by_metabolic_syndrome",
        "participation_by_age",
        "positive_wins",
    }
)

# Engine ``concerns`` keys → camp section key (1:1 narratives).
_CONCERN_TO_SECTION: Mapping[str, str] = {
    "overall_risk": "overall_risk_score",
    "physical_activity": "distribution_by_physical_activity_frequency",
    "sleep": "distribution_by_sleeping_hours",
    "oxidative_stress": "distribution_by_oxidative_stress",
    "participation": "participation_by_age",
}

_SECTION_ALIASES: Mapping[str, str] = {
    **{camp_key: camp_key for camp_key in INTELLIGENCE_CAMP_SECTIONS},
    **_CONCERN_TO_SECTION,
    "disease_risks": "distribution_by_gender_by_metabolic_syndrome",
    "disease_deep_dive": "distribution_by_gender_by_metabolic_syndrome",
    "gender_comparison": "distribution_by_gender_by_metabolic_syndrome",
    "positive_highlights": "positive_wins",
    "positives": "positive_wins",
    "leadership_takeaways": "leadership_takeaways",
    "leadership_cards": "leadership_takeaways",
    "leadership": "leadership_takeaways",
}


def resolve_intelligence_section(section: str) -> str:
    normalized = (section or "").strip()
    if not normalized:
        raise ValueError("section is required")
    camp_key = _SECTION_ALIASES.get(normalized)
    if camp_key is None:
        raise ValueError(f"unsupported intelligence section: {normalized}")
    return camp_key


def enrich_camp_report_with_intelligence(report: dict) -> dict:
    """Return a deep copy of ``report`` with section-level ``intelligence`` attached.

    Preserves existing section ``data``, ``name``, and ``description``.
    Does not include ``profile`` or ``leadership_cards`` in the camp JSON.
    Attached ``intelligence`` is the frontend contract only (tone /
    observation / explanation / recommendation); engine metadata stays on
    the internal ``generate_report_insights`` payload.

    Unmapped sections (``kpis``, ``blood_and_lab_intelligence``,
    ``company_average_scores``, ``ranking``, ``meta``, …) are left unchanged.

    Adds generated ``leadership_takeaways`` (source engine ``leadership_cards``).
    """
    if not isinstance(report, dict):
        raise TypeError("report must be a dict")

    enriched: Dict[str, Any] = copy.deepcopy(report)
    insights = generate_report_insights(report)
    concerns = insights.get("concerns") or {}
    if not isinstance(concerns, dict):
        concerns = {}

    for concern_key, section_key in _CONCERN_TO_SECTION.items():
        if concern_key not in concerns:
            continue
        _attach_intelligence(enriched, section_key, concerns[concern_key])

    metabolic_intel = _metabolic_intelligence(concerns)
    if metabolic_intel is not None:
        _attach_intelligence(
            enriched,
            "distribution_by_gender_by_metabolic_syndrome",
            metabolic_intel,
        )

    positives_intel = _positives_intelligence(enriched)
    if positives_intel is not None:
        _attach_intelligence(enriched, "positive_wins", positives_intel)

    _attach_leadership_takeaways(enriched, insights)
    return enriched


def generate_camp_section_intelligence(report: dict, section: str) -> tuple[str, Any]:
    if not isinstance(report, dict):
        raise TypeError("report must be a dict")

    camp_key = resolve_intelligence_section(section)
    if camp_key == "distribution_by_gender_by_metabolic_syndrome":
        disease_risks = generate_section_insights(report, "disease_risks")
        deep_dive = generate_section_insights(report, "disease_deep_dive")
        concerns = {
            **(disease_risks.get("concerns") or {}),
            **(deep_dive.get("concerns") or {}),
        }
        intelligence = _metabolic_intelligence(concerns)
    elif camp_key == "positive_wins":
        intelligence = _positives_intelligence(report)
    elif camp_key == LEADERSHIP_TAKEAWAYS_SECTION:
        insights = generate_report_insights(report)
        intelligence = _leadership_intelligence_from_insights(insights)
    else:
        concern_key = next(
            (engine_id for engine_id, mapped in _CONCERN_TO_SECTION.items() if mapped == camp_key),
            None,
        )
        if concern_key is None:
            raise ValueError(f"unsupported intelligence section: {section}")
        insights = generate_section_insights(report, concern_key)
        concerns = insights.get("concerns") or {}
        intelligence = concerns.get(concern_key)

    if intelligence is None:
        raise ValueError(f"no intelligence produced for section: {section}")
    return camp_key, _unique_nested_statements(_public_intelligence(intelligence))


def _metabolic_intelligence(concerns: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    payload: Dict[str, Any] = {}
    if "disease_risks" in concerns:
        payload["disease_risks"] = concerns["disease_risks"]
    if "disease_deep_dive" in concerns:
        payload["disease_deep_dive"] = concerns["disease_deep_dive"]
    return payload or None


def _positives_intelligence(report: Mapping[str, Any] | None) -> Optional[Dict[str, Any]]:
    """One statement per frontend Positive Wins card. Always returns all three cards."""
    section = (report or {}).get("positive_wins") if isinstance(report, Mapping) else None
    data = section.get("data") if isinstance(section, Mapping) else None
    if not isinstance(data, Mapping):
        data = {}

    diseases = _positive_win_names(data.get("low_risk"), name_keys=("name", "code", "label"))
    habits = _positive_win_names(
        data.get("healthy_habits"),
        name_keys=("habit_label", "habit_key", "name", "label"),
    )
    profiles = _positive_win_names(
        data.get("healthy_profiles"),
        name_keys=("name", "profile", "profile_name", "label", "title", "group_name"),
    )

    return {
        "low_risk_diseases": _positive_bucket_narrative(
            "low_risk_diseases",
            diseases,
            [
                "{items} are currently in healthy or low-risk bands for this camp. Keep routine screening in place so these areas stay protected.",
                "Low-risk disease areas in this workforce include {items}. Continue the prevention work that is holding these conditions in a healthy range.",
            ],
            empty="No low-risk diseases were identified in this camp's current dataset. This card will populate when qualifying disease results are available.",
        ),
        "healthy_habits": _positive_bucket_narrative(
            "healthy_habits",
            habits,
            [
                "Healthy habits showing through in this camp include {items}. Reinforce these behaviours in everyday wellbeing programmes.",
                "This workforce is doing well on {items}. Keep supporting these habits so they remain the default.",
            ],
            empty="No healthy habits were identified in this camp's current dataset. This card will populate when qualifying habit results are available.",
        ),
        "healthy_blood_profiles": _positive_bucket_narrative(
            "healthy_blood_profiles",
            profiles,
            [
                "Healthy blood profiles for this camp include {items}. Maintain the testing cadence that is keeping these panels in range.",
                "In-range lab profiles include {items}. Continue the follow-up that is protecting these blood markers.",
            ],
            empty="No healthy blood profiles were identified in this camp's current dataset. This card will populate when qualifying lab results are available.",
        ),
    }


def _positive_win_names(raw: Any, *, name_keys: tuple[str, ...]) -> list[str]:
    names: list[str] = []
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if not isinstance(raw, list):
        return names
    for item in raw:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
            continue
        if not isinstance(item, Mapping):
            continue
        label = ""
        keys = name_keys or ("name", "label", "title")
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                label = value.strip()
                break
        if label:
            names.append(label)
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


def _join_english(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _positive_bucket_narrative(
    bucket_id: str,
    items: list[str],
    templates: list[str],
    empty: str,
) -> Dict[str, str]:
    if not items:
        return {"tone": "neutral", "statement": empty}
    listed = _join_english(items)
    index = sum(ord(ch) for ch in f"{bucket_id}|{listed}") % len(templates)
    statement = templates[index].format(items=listed)
    return {"tone": "positive", "statement": statement}


LEADERSHIP_TAKEAWAYS_SECTION = "leadership_takeaways"

_PUBLIC_LEADERSHIP_CARD_KEYS: tuple[str, ...] = (
    "tone",
    "statement",
)


def _leadership_intelligence_from_insights(insights: Mapping[str, Any]) -> Dict[str, Any]:
    raw_cards = insights.get("leadership_cards") or []
    if not isinstance(raw_cards, list):
        return {}
    out: Dict[str, Any] = {}
    used_sentences: set[str] = set()
    for card in raw_cards:
        if not isinstance(card, Mapping):
            continue
        key = str(card.get("id") or "").replace("-", "_") or f"card_{len(out) + 1}"
        narrative = _public_narrative(card)
        statement = _drop_used_sentences(narrative.get("statement") or "", used_sentences)
        if not statement:
            continue
        out[key] = {"tone": narrative.get("tone") or "", "statement": statement}
    return _unique_nested_statements(out)


def _drop_used_sentences(text: str, used: set[str]) -> str:
    kept: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        sentence = part.strip()
        if not sentence:
            continue
        key = re.sub(r"[.!,;:]+$", "", " ".join(sentence.lower().split())).strip()
        if not key or key in used:
            continue
        used.add(key)
        kept.append(sentence)
    return " ".join(kept)


def _unique_nested_statements(payload: Any) -> Any:
    """No sentence is reused across sibling narratives in one section payload."""
    used: set[str] = set()

    def walk(node: Any) -> Any:
        if isinstance(node, Mapping) and "statement" in node and "tone" in node:
            statement = _drop_used_sentences(str(node.get("statement") or ""), used)
            if not statement:
                return dict(node)
            out = dict(node)
            out["statement"] = statement
            return out
        if isinstance(node, Mapping):
            return {str(key): walk(value) for key, value in node.items()}
        return node

    return walk(payload)


def _attach_leadership_takeaways(
    report: MutableMapping[str, Any],
    insights: Mapping[str, Any],
) -> None:
    """Source ``leadership_cards`` → camp section ``leadership_takeaways``."""
    intelligence = _leadership_intelligence_from_insights(insights)
    existing = report.get(LEADERSHIP_TAKEAWAYS_SECTION)
    section: Dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    section.setdefault("name", "Leadership Takeaways")
    section.setdefault(
        "description",
        "Workforce-level leadership observations and strategic next steps.",
    )
    section.setdefault("data", {})
    section["intelligence"] = intelligence
    report[LEADERSHIP_TAKEAWAYS_SECTION] = section


def build_leadership_takeaways_section(report: dict) -> dict:
    insights = generate_report_insights(report)
    out: Dict[str, Any] = {}
    _attach_leadership_takeaways(out, insights)
    return out[LEADERSHIP_TAKEAWAYS_SECTION]


# Frontend dashboard contract. Internal engine metadata is calculated and
# retained on ``generate_report_insights``; it is stripped only here.
_PUBLIC_NARRATIVE_KEYS: tuple[str, str] = (
    "tone",
    "statement",
)


def _is_engine_narrative(payload: Mapping[str, Any]) -> bool:
    """True for a serialized ChartNarrative or leadership card."""
    if "structured" in payload:
        return True
    if "tone" in payload and (
        "text" in payload or "observation" in payload or "statement" in payload or "body" in payload
    ):
        return True
    return False


def _combine_statement(*parts: str) -> str:
    seen: set[str] = set()
    sentences: list[str] = []
    for part in parts:
        text = " ".join(str(part or "").split()).strip()
        if not text:
            continue
        if text[-1] not in ".!?":
            text += "."
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        sentences.append(text)
    return " ".join(sentences)


def _public_narrative(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Frontend contract: tone plus a single combined statement."""
    structured = payload.get("structured")
    structured = structured if isinstance(structured, Mapping) else {}
    observation = structured.get("observation") or payload.get("observation") or ""
    explanation = structured.get("explanation") or payload.get("explanation") or ""
    recommendation = structured.get("recommendation") or payload.get("recommendation") or ""
    body = payload.get("body") or payload.get("text") or ""
    statement = payload.get("statement") or ""
    if not statement:
        if observation or explanation or recommendation:
            statement = _combine_statement(observation, explanation, recommendation)
        else:
            statement = _combine_statement(body)
    return {
        "tone": payload.get("tone") or structured.get("tone") or "",
        "statement": statement,
    }


def _public_intelligence(payload: Any) -> Any:
    """Recursively expose only frontend fields; keep nested section maps."""
    if not isinstance(payload, Mapping):
        return payload
    if _is_engine_narrative(payload):
        return _public_narrative(payload)
    return {str(key): _public_intelligence(value) for key, value in payload.items()}


def _attach_intelligence(
    report: MutableMapping[str, Any],
    section_key: str,
    intelligence: Any,
) -> None:
    """Attach intelligence only if the section already exists as a dict."""
    section = report.get(section_key)
    if not isinstance(section, dict):
        return
    section["intelligence"] = _unique_nested_statements(
        _public_intelligence(intelligence)
    )
