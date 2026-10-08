"""Static Orange Health D2C test catalog for admin parameter mapping."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_D2C_TESTS_PATH = Path(__file__).resolve().parent / "d2c_tests.json"


@lru_cache(maxsize=1)
def load_d2c_tests() -> list[dict[str, str]]:
    with _D2C_TESTS_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("d2c_tests.json must be a JSON array")
    return data
