"""Super Club sport catalog (matches SapnaShyft early-access MCQ)."""

from __future__ import annotations

SUPERCLUB_SPORT_CATALOG: list[dict[str, str]] = [
    {"id": "pickleball", "label": "Pickle ball"},
    {"id": "padel", "label": "Padel"},
    {"id": "calisthenics", "label": "Calisthenics"},
    {"id": "functional", "label": "Functional Training"},
    {"id": "pilates", "label": "Pilates Workshop"},
    {"id": "hyrox", "label": "Hyrox Workshop"},
    {"id": "football", "label": "Football"},
    {"id": "running", "label": "Running Clubs"},
    {"id": "cycling", "label": "Cycling"},
    {"id": "yoga", "label": "Yoga & Meditation"},
    {"id": "badminton", "label": "Badminton"},
    {"id": "cricket", "label": "Turf Cricket"},
]

SUPERCLUB_SPORT_LABELS: dict[str, str] = {
    item["id"]: item["label"] for item in SUPERCLUB_SPORT_CATALOG
}


def normalize_sports_playlists(raw: object | None) -> dict[str, object]:
    if not raw or not isinstance(raw, dict):
        return {"sportIds": [], "otherSelected": False, "otherNote": ""}
    sport_ids = raw.get("sportIds")
    if not isinstance(sport_ids, list):
        sport_ids = []
    return {
        "sportIds": [str(item) for item in sport_ids if str(item).strip()],
        "otherSelected": bool(raw.get("otherSelected")),
        "otherNote": str(raw.get("otherNote") or ""),
    }


def has_submitted_playlist(normalized: dict[str, object]) -> bool:
    sport_ids = normalized.get("sportIds")
    if isinstance(sport_ids, list) and len(sport_ids) > 0:
        return True
    return bool(normalized.get("otherSelected"))
