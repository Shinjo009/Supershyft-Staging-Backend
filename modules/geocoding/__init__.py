"""Geocoding helpers (Nominatim + Google with fallback).

Import client functions from ``modules.geocoding.client`` directly. This package
``__init__`` must not import ``client`` (it pulls audit logging and breaks app
startup via a circular import through ``platform_settings`` → ``geocoding``).
"""

from modules.geocoding.enums import GeocodingProvider

__all__ = ["GeocodingProvider"]
