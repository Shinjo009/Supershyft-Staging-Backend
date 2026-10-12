"""Public expert card fields: partner name, discount, weekly availability summary."""

from __future__ import annotations

from collections import defaultdict
from datetime import time
from typing import Any

from modules.experts.models import Expert, ExpertAvailabilityModel

_DAY_LABELS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def compute_discount_percent(
    appointment_fee_paise: int | None,
    original_fee_paise: int | None,
) -> int | None:
    if appointment_fee_paise is None or original_fee_paise is None:
        return None
    if original_fee_paise <= appointment_fee_paise or original_fee_paise <= 0:
        return None
    return int(round((original_fee_paise - appointment_fee_paise) / original_fee_paise * 100))


def _time_to_hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def _format_clock_12h(t: time) -> str:
    hour = t.hour
    minute = t.minute
    period = "AM" if hour < 12 else "PM"
    h12 = hour % 12
    if h12 == 0:
        h12 = 12
    if minute == 0:
        return f"{h12} {period}"
    return f"{h12}:{minute:02d} {period}"


def _format_hours_label(start: time, end: time) -> str:
    start_s = _format_clock_12h(start)
    end_s = _format_clock_12h(end)
    if start.minute == 0 and end.minute == 0:
        start_part = start_s.replace(" AM", "").replace(" PM", "")
        return f"{start_part}-{end_s}"
    return f"{start_s}-{end_s}"


def _format_day_label(days: list[int]) -> str:
    if not days:
        return ""
    unique = sorted(set(days))
    runs: list[tuple[int, int]] = []
    run_start = unique[0]
    run_end = unique[0]
    for day in unique[1:]:
        if day == run_end + 1:
            run_end = day
        else:
            runs.append((run_start, run_end))
            run_start = day
            run_end = day
    runs.append((run_start, run_end))

    parts: list[str] = []
    for start, end in runs:
        if start == end:
            parts.append(_DAY_LABELS[start])
        else:
            parts.append(f"{_DAY_LABELS[start]}-{_DAY_LABELS[end]}")
    return ", ".join(parts)


def summarize_weekly_availability(blocks: list[ExpertAvailabilityModel]) -> dict[str, Any] | None:
    if not blocks:
        return None

    by_window: dict[tuple[str, str], list[int]] = defaultdict(list)
    for block in blocks:
        if block.start_time is None or block.end_time is None:
            continue
        key = (_time_to_hhmm(block.start_time), _time_to_hhmm(block.end_time))
        by_window[key].append(block.day_of_week)

    if not by_window:
        return None

    all_days = sorted({d for days in by_window.values() for d in days})
    base: dict[str, Any] = {
        "days": all_days,
        "day_label": _format_day_label(all_days),
    }

    if len(by_window) == 1:
        (start_hhmm, end_hhmm), window_days = next(iter(by_window.items()))
        start_parts = start_hhmm.split(":")
        end_parts = end_hhmm.split(":")
        start_t = time(int(start_parts[0]), int(start_parts[1]))
        end_t = time(int(end_parts[0]), int(end_parts[1]))
        base["days"] = sorted(set(window_days))
        base["day_label"] = _format_day_label(base["days"])
        base["start_time"] = start_hhmm
        base["end_time"] = end_hhmm
        base["hours_label"] = _format_hours_label(start_t, end_t)
        return base

    base["start_time"] = None
    base["end_time"] = None
    base["hours_label"] = None
    windows: list[dict[str, Any]] = []
    for (start_hhmm, end_hhmm), window_days in sorted(by_window.items(), key=lambda item: min(item[1])):
        start_parts = start_hhmm.split(":")
        end_parts = end_hhmm.split(":")
        start_t = time(int(start_parts[0]), int(start_parts[1]))
        end_t = time(int(end_parts[0]), int(end_parts[1]))
        days_sorted = sorted(set(window_days))
        windows.append(
            {
                "days": days_sorted,
                "day_label": _format_day_label(days_sorted),
                "start_time": start_hhmm,
                "end_time": end_hhmm,
                "hours_label": _format_hours_label(start_t, end_t),
            }
        )
    base["windows"] = windows
    return base


def card_fields_for_expert(
    expert: Expert,
    *,
    partner_name: str | None,
    availability_blocks: list[ExpertAvailabilityModel],
) -> dict[str, Any]:
    return {
        "name": partner_name,
        "discount_percent": compute_discount_percent(
            expert.appointment_fee_paise,
            expert.original_fee_paise,
        ),
        "availability": summarize_weekly_availability(availability_blocks),
    }
