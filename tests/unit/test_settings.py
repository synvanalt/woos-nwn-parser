"""Unit tests for app settings persistence helpers."""

import json
import shutil
import uuid
from pathlib import Path

from app.settings import AppSettings, get_settings_path, load_app_settings, save_app_settings


def _make_test_dir() -> Path:
    base = Path("tests-round-time") / "settings-tests"
    base.mkdir(parents=True, exist_ok=True)
    path = base / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    return path


def test_get_settings_path_prefers_local_app_data(monkeypatch) -> None:
    tmp_path = _make_test_dir()
    try:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        path = get_settings_path()

        assert path == tmp_path / "WoosNwnParser" / "settings.json"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_app_settings_returns_defaults_when_missing() -> None:
    tmp_path = _make_test_dir()
    try:
        settings = load_app_settings(tmp_path / "missing.json")

        assert settings == AppSettings()
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_app_settings_reads_expected_values() -> None:
    tmp_path = _make_test_dir()
    try:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "log_directory": "  C:\\logs  ",
                    "death_fallback_line": "  Your God refuses to hear your prayers!  ",
                    "parse_immunity": False,
                    "first_timestamp_mode": " global ",
                }
            ),
            encoding="utf-8",
        )

        settings = load_app_settings(path)

        assert settings.log_directory == r"C:\logs"
        assert settings.death_fallback_line == "Your God refuses to hear your prayers!"
        assert settings.parse_immunity is False
        assert settings.first_timestamp_mode == "global"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_app_settings_invalid_json_returns_defaults() -> None:
    tmp_path = _make_test_dir()
    try:
        path = tmp_path / "settings.json"
        path.write_text("{not-json", encoding="utf-8")

        settings = load_app_settings(path)

        assert settings == AppSettings()
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_save_app_settings_round_trip() -> None:
    tmp_path = _make_test_dir()
    try:
        path = tmp_path / "settings.json"
        expected = AppSettings(
            log_directory=r"C:\new_logs",
            death_fallback_line="Custom fallback line",
            parse_immunity=True,
            first_timestamp_mode="per_character",
        )

        save_app_settings(expected, path)
        actual = load_app_settings(path)

        assert actual == expected
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_app_settings_missing_parse_immunity_key_returns_none_for_app_defaulting() -> None:
    tmp_path = _make_test_dir()
    try:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "log_directory": r"C:\logs",
                    "death_fallback_line": "Custom fallback line",
                }
            ),
            encoding="utf-8",
        )

        settings = load_app_settings(path)

        assert settings.parse_immunity is None
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_app_settings_invalid_parse_immunity_returns_none() -> None:
    tmp_path = _make_test_dir()
    try:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "parse_immunity": "yes",
                }
            ),
            encoding="utf-8",
        )

        settings = load_app_settings(path)

        assert settings.parse_immunity is None
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_app_settings_missing_first_timestamp_mode_returns_none() -> None:
    tmp_path = _make_test_dir()
    try:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "parse_immunity": True,
                }
            ),
            encoding="utf-8",
        )

        settings = load_app_settings(path)

        assert settings.first_timestamp_mode is None
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_app_settings_invalid_first_timestamp_mode_returns_none() -> None:
    tmp_path = _make_test_dir()
    try:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "first_timestamp_mode": "partywide",
                }
            ),
            encoding="utf-8",
        )

        settings = load_app_settings(path)

        assert settings.first_timestamp_mode is None
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
