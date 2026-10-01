"""Geocoding provider enums."""

from __future__ import annotations

import enum


class GeocodingProvider(str, enum.Enum):
    google = "google"
    nominatim = "nominatim"
