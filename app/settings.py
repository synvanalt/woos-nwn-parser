"""User settings persistence helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppSettings:
    """Persisted user settings."""

    log_directory: str | None = None
    death_fallback_line: str | None = None
    parse_immunity: bool | None = None
    first_timestamp_mode: str | None = None


def get_settings_path() -> Path:
    """Return the per-user settings file path."""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        base_dir = Path(local_app_data)
    else:
        base_dir = Path.home() / ".woos-nwn-parser"
    return base_dir / "WoosNwnParser" / "settings.json"


def _normalize_optional_text(value: Any) -> str | None:
    """Normalize optional text values loaded from JSON."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_optional_bool(value: Any) -> bool | None:
    """Normalize optional boolean values loaded from JSON."""
    if isinstance(value, bool):
        return value
    return None


def _normalize_optional_first_timestamp_mode(value: Any) -> str | None:
    """Normalize persisted first timestamp mode values loaded from JSON."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"per_character", "global"}:
        return normalized
    return None


def load_app_settings(path: Path | None = None) -> AppSettings:
    """Load persisted app settings from disk."""
    settings_path = path or get_settings_path()
    try:
        content = settings_path.read_text(encoding="utf-8")
        payload = json.loads(content)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return AppSettings()

    if not isinstance(payload, dict):
        return AppSettings()

    return AppSettings(
        log_directory=_normalize_optional_text(payload.get("log_directory")),
        death_fallback_line=_normalize_optional_text(payload.get("death_fallback_line")),
        parse_immunity=_normalize_optional_bool(payload.get("parse_immunity")),
        first_timestamp_mode=_normalize_optional_first_timestamp_mode(
            payload.get("first_timestamp_mode")
        ),
    )


def save_app_settings(settings: AppSettings, path: Path | None = None) -> None:
    """Persist app settings to disk."""
    settings_path = path or get_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "log_directory": _normalize_optional_text(settings.log_directory),
        "death_fallback_line": _normalize_optional_text(settings.death_fallback_line),
        "parse_immunity": (
            _normalize_optional_bool(settings.parse_immunity)
            if settings.parse_immunity is not None
            else None
        ),
        "first_timestamp_mode": _normalize_optional_first_timestamp_mode(
            settings.first_timestamp_mode
        ),
    }
    settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
