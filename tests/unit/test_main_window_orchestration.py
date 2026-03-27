"""Integration-oriented orchestration tests for WoosNwnParserApp."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import Mock

import pytest

import app.ui.main_window as main_window_module
from app.settings import AppSettings
from app.ui.main_window import WoosNwnParserApp
from app.ui.runtime_config import DEFAULT_APP_RUNTIME_CONFIG


def _make_app_shell() -> WoosNwnParserApp:
    app = WoosNwnParserApp.__new__(WoosNwnParserApp)
    app.runtime_config = DEFAULT_APP_RUNTIME_CONFIG
    app.data_store = Mock(get_all_targets=Mock(return_value=["Goblin", "Orc"]), close=Mock())
    app.immunity_panel = Mock()
    app.immunity_panel.target_combo.get.return_value = ""
    app.immunity_panel.target_combo.current = Mock()
    app.immunity_panel.update_target_list = Mock()
    app.dps_panel = Mock()
    app.dps_panel.update_target_filter_options = Mock()
    app.dps_panel.refresh = Mock()
    app.stats_panel = Mock(refresh=Mock())
    app.settings_controller = Mock()
    app.import_controller = Mock(shutdown=Mock())
    app.monitor_controller = Mock(shutdown=Mock())
    app.tooltip_manager = Mock(destroy=Mock())
    app.root = Mock(destroy=Mock())
    app._is_closing = False
    return app


@pytest.fixture
def app_shell() -> WoosNwnParserApp:
    return _make_app_shell()


def test_browse_directory_delegates_to_monitor_controller(app_shell) -> None:
    app_shell.browse_directory()
    app_shell.monitor_controller.browse_for_directory.assert_called_once_with()


def test_load_and_parse_delegates_to_import_controller_with_monitor_state(app_shell) -> None:
    app_shell.monitor_controller.is_monitoring = True

    app_shell.load_and_parse_selected_files()

    app_shell.import_controller.start_from_dialog.assert_called_once_with(is_monitoring=True)


def test_abort_load_parse_delegates_to_import_controller(app_shell) -> None:
    app_shell.abort_load_parse()
    app_shell.import_controller.abort.assert_called_once_with()


def test_refresh_targets_reads_target_list_once_and_updates_all_dependents(app_shell) -> None:
    app_shell.refresh_targets()

    app_shell.data_store.get_all_targets.assert_called_once_with()
    app_shell.immunity_panel.update_target_list.assert_called_once_with(["Goblin", "Orc"])
    app_shell.dps_panel.update_target_filter_options.assert_called_once_with(["Goblin", "Orc"])
    app_shell.stats_panel.refresh.assert_called_once_with()
    app_shell.immunity_panel.target_combo.current.assert_called_once_with(0)


def test_on_closing_shuts_down_controllers_in_order(app_shell) -> None:
    calls: list[str] = []
    app_shell.settings_controller.flush_pending_save.side_effect = lambda: calls.append("settings")
    app_shell.import_controller.shutdown.side_effect = lambda: calls.append("import")
    app_shell.monitor_controller.shutdown.side_effect = lambda: calls.append("monitor")
    app_shell.data_store.close.side_effect = lambda: calls.append("data_store")
    app_shell.tooltip_manager.destroy.side_effect = lambda: calls.append("tooltips")
    app_shell.root.destroy.side_effect = lambda: calls.append("root")

    app_shell.on_closing()

    assert calls == ["settings", "import", "monitor", "data_store", "tooltips", "root"]


def test_on_closing_is_reentrant_safe(app_shell) -> None:
    app_shell.on_closing()
    app_shell.on_closing()

    app_shell.settings_controller.flush_pending_save.assert_called_once_with()
    app_shell.import_controller.shutdown.assert_called_once_with()
    app_shell.monitor_controller.shutdown.assert_called_once_with()
    app_shell.data_store.close.assert_called_once_with()
    app_shell.root.destroy.assert_called_once_with()


def test_time_tracking_mode_change_refreshes_when_mode_changes(app_shell) -> None:
    app_shell.dps_query_service = Mock(time_tracking_mode="per_character", set_time_tracking_mode=Mock())
    app_shell.dps_panel.time_tracking_var = Mock(get=Mock(return_value="Global"))
    app_shell._schedule_session_settings_save = Mock()
    event = Mock(widget=Mock())

    app_shell._on_time_tracking_mode_changed(event)

    event.widget.selection_clear.assert_called_once_with()
    app_shell.dps_query_service.set_time_tracking_mode.assert_called_once_with("global")
    app_shell._schedule_session_settings_save.assert_called_once_with()
    app_shell.dps_panel.refresh.assert_called_once_with()


def test_restore_persisted_dps_panel_state_sets_combobox_label(app_shell) -> None:
    app_shell.dps_query_service = Mock(time_tracking_mode="global")
    app_shell.dps_panel.time_tracking_var = Mock()

    app_shell._restore_persisted_dps_panel_state()

    app_shell.dps_panel.time_tracking_var.set.assert_called_once_with("Global")


def test_init_uses_persisted_settings_over_defaults(monkeypatch) -> None:
    root = Mock()
    root.after = Mock()
    root.title = Mock()
    root.geometry = Mock()

    monkeypatch.setattr(
        main_window_module,
        "load_app_settings",
        lambda: AppSettings(
            log_directory=r"C:\persisted_logs",
            death_fallback_line="Persisted fallback",
            parse_immunity=False,
            first_timestamp_mode="global",
        ),
    )
    monkeypatch.setattr(main_window_module, "get_default_log_directory", lambda: r"C:\default_logs")
    monkeypatch.setattr(main_window_module.font, "nametofont", lambda _name: Mock())
    monkeypatch.setattr(WoosNwnParserApp, "setup_ui", lambda self: None)
    monkeypatch.setattr(main_window_module.SessionSettingsController, "load_initial_settings", lambda self: AppSettings(
        log_directory=r"C:\persisted_logs",
        death_fallback_line="Persisted fallback",
        parse_immunity=False,
        first_timestamp_mode="global",
    ))
    monkeypatch.setattr(WoosNwnParserApp, "_set_monitoring_switch_ui", lambda self, _value: None)

    app = WoosNwnParserApp(root)

    assert app.log_directory == r"C:\persisted_logs"
    assert app._initial_death_fallback_line == "Persisted fallback"
    assert app.parser.parse_immunity is False
    assert app.dps_query_service.time_tracking_mode == "global"


def test_init_defaults_parse_immunity_on_when_setting_missing(monkeypatch) -> None:
    root = Mock()
    root.after = Mock()
    root.title = Mock()
    root.geometry = Mock()

    monkeypatch.setattr(main_window_module, "load_app_settings", lambda: AppSettings())
    monkeypatch.setattr(main_window_module, "get_default_log_directory", lambda: r"C:\default_logs")
    monkeypatch.setattr(main_window_module.font, "nametofont", lambda _name: Mock())
    monkeypatch.setattr(WoosNwnParserApp, "setup_ui", lambda self: None)
    monkeypatch.setattr(WoosNwnParserApp, "_set_monitoring_switch_ui", lambda self, _value: None)

    app = WoosNwnParserApp(root)

    assert app.parser.parse_immunity is True


def test_init_uses_runtime_config_for_queue_maxsize(monkeypatch) -> None:
    root = Mock()
    root.after = Mock()
    root.title = Mock()
    root.geometry = Mock()

    monkeypatch.setattr(main_window_module, "load_app_settings", lambda: AppSettings())
    monkeypatch.setattr(main_window_module, "get_default_log_directory", lambda: r"C:\default_logs")
    monkeypatch.setattr(main_window_module.font, "nametofont", lambda _name: Mock())
    monkeypatch.setattr(WoosNwnParserApp, "setup_ui", lambda self: None)
    monkeypatch.setattr(WoosNwnParserApp, "_set_monitoring_switch_ui", lambda self, _value: None)

    app = WoosNwnParserApp(root)

    assert app.data_queue.maxsize == DEFAULT_APP_RUNTIME_CONFIG.queue.data_queue_maxsize
