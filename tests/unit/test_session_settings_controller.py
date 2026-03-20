"""Unit tests for SessionSettingsController."""

from unittest.mock import Mock

from app.settings import AppSettings
from app.ui.controllers.session_settings_controller import SessionSettingsController


def test_build_settings_reads_current_callbacks() -> None:
    parser = Mock()
    parser.parse_immunity = False
    controller = SessionSettingsController(
        root=None,
        parser=parser,
        dps_service=Mock(),
        get_log_directory=lambda: r"C:\logs",
        get_death_fallback_line=lambda: "fallback line",
        get_first_timestamp_mode=lambda: "global",
    )

    settings = controller.build_settings()

    assert settings == AppSettings(
        log_directory=r"C:\logs",
        death_fallback_line="fallback line",
        parse_immunity=False,
        first_timestamp_mode="global",
    )


def test_schedule_save_debounces_and_flushes() -> None:
    root = Mock()
    root.after = Mock(return_value="new-job")
    root.after_cancel = Mock()
    save_settings = Mock()
    controller = SessionSettingsController(
        root=root,
        parser=Mock(parse_immunity=True),
        dps_service=Mock(),
        get_log_directory=lambda: "",
        get_death_fallback_line=lambda: "",
        get_first_timestamp_mode=lambda: "per_character",
        save_settings=save_settings,
    )
    controller._settings_save_job = "old-job"

    controller.schedule_save()
    controller.flush_pending_save()

    root.after_cancel.assert_called_once_with("old-job")
    root.after.assert_called_once_with(400, controller.flush_pending_save)
    save_settings.assert_called_once()
