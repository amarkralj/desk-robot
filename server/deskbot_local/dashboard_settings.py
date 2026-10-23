"""Validated DeskBot-only preferences, stored separately from brain settings."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .registry import default_data_directory

SETTINGS_PATH = default_data_directory() / "deskbot-settings.json"
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DEFAULTS: dict[str, Any] = {
    "language": "en",
    "spontaneous_events_enabled": False,
    "min_event_interval_minutes": 45,
    "max_event_interval_minutes": 120,
    "active_start": "08:00",
    "active_end": "16:00",
    "quiet_mode": False,
    "touch_sensitivity": 50,
    "privacy_mode": True,
    "recognition_enabled": False,
}


class DeskBotSettingsStore:
    """Read/update/export offline preferences without touching brain settings."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = SETTINGS_PATH if path is None else Path(path)

    def load(self) -> dict[str, Any]:
        result = dict(DEFAULTS)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return result
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read DeskBot settings: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("DeskBot settings file must contain a JSON object")
        return self._merge_validated(result, raw)

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(changes, dict):
            raise ValueError("changes must be a JSON object")
        merged = self._merge_validated(self.load(), changes)
        self._write(merged)
        return merged

    def export(self) -> dict[str, Any]:
        return self.load()

    @staticmethod
    def _merge_validated(current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        unknown = set(changes) - DEFAULTS.keys()
        if unknown:
            raise ValueError(f"unknown DeskBot setting(s): {', '.join(sorted(unknown))}")
        result = dict(current)
        for key, value in changes.items():
            result[key] = _clean_setting(key, value)
        minimum = result["min_event_interval_minutes"]
        maximum = result["max_event_interval_minutes"]
        if maximum < minimum:
            raise ValueError("maximum event interval must be at least the minimum")
        if result["recognition_enabled"] and result["privacy_mode"]:
            raise ValueError("turn off privacy mode before enabling recognition")
        return result

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            os.chmod(self.path.parent, 0o700)
        fd, temporary_name = tempfile.mkstemp(prefix=".deskbot-settings-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(value, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            if os.name == "posix":
                os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise


def _clean_setting(key: str, value: Any) -> Any:
    if key in {"language"}:
        if not isinstance(value, str) or value not in {"de", "en"}:
            raise ValueError("language must be 'de' or 'en'")
        return value
    if key in {
        "spontaneous_events_enabled",
        "quiet_mode",
        "privacy_mode",
        "recognition_enabled",
    }:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if key in {"active_start", "active_end"}:
        if not isinstance(value, str) or not _TIME.fullmatch(value):
            raise ValueError(f"{key} must be a time like 08:00")
        return value
    if key in {"min_event_interval_minutes", "max_event_interval_minutes"}:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1440:
            raise ValueError(f"{key} must be a whole number from 1 to 1440")
        return value
    if key == "touch_sensitivity":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError("touch_sensitivity must be a whole number from 0 to 100")
        return value
    raise ValueError(f"unsupported DeskBot setting: {key}")
