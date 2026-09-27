"""Enums for participant_blood_bookings."""

from __future__ import annotations

from enum import StrEnum


class BloodBookingRelation(StrEnum):
    primary = "primary"
    resample = "resample"
    redraw = "redraw"
    reschedule = "reschedule"


class BloodBookingStatus(StrEnum):
    active = "active"
    superseded = "superseded"
    cancelled = "cancelled"
