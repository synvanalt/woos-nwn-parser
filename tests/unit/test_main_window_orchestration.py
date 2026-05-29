"""Integration-oriented orchestration tests for WoosNwnParserApp."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import Mock

import pytest

import app.ui.main_window as main_window_module
from app.parser import ParserSession
from app.settings import AppSettings
from app.ui.main_window import WoosNwnParserApp
from app.ui.runtime_config import DEFAULT_APP_RUNTIME_CONFIG


def _mock_setup_ui(app: WoosNwnParserApp) -> None:
    app.notebook = Mock(bind=Mock())
    app.dps_panel = Mock()
    app.dps_panel.time_tracking_var = Mock(set=Mock(), get=Mock(return_value="Per Character"))
    app.dps_panel.time_tracking_combo = Mock(bind=Mock())
    app.dps_panel.target_filter_combo = Mock(bind=Mock())
    app.dps_panel.include_summons_check = Mock(configure=Mock())
    app.dps_panel.get_include_summons_in_dps = Mock(return_value=False)
    app.dps_panel.set_include_summons_in_dps = Mock()
    app.stats_panel = Mock()
    app.immunity_panel = Mock()
    app.immunity_panel.target_combo = Mock(bind=Mock(), get=Mock(return_value=""))
    app.death_snippet_panel = Mock()
    app.death_snippet_panel.get_character_name.return_value = ""
    app.death_snippet_panel.get_fallback_death_line.return_value = ParserSession.DEFAULT_DEATH_FALLBACK_LINE
    app.debug_panel = Mock()
    app.debug_panel.debug_mode_var = Mock(trace=Mock())


def _patch_init_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(WoosNwnParserApp, "setup_ui", _mock_setup_ui)
    monkeypatch.setattr(WoosNwnParserApp, "_set_monitoring_switch_ui", lambda self, _value: None)
    monkeypatch.setattr(main_window_module, "RefreshCoordinator", Mock(return_value=Mock()))
    monkeypatch.setattr(main_window_module, "QueueDrainController", Mock(return_value=Mock(start=Mock())))
    monkeypatch.setattr(main_window_module, "MonitorController", Mock(return_value=Mock(configure_switch_style=Mock())))
    monkeypatch.setattr(main_window_module, "ImportController", Mock(return_value=Mock()))
    monkeypatch.setattr(main_window_module, "DebugUnlockController", Mock(return_value=Mock()))


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
    app.dps_panel.get_include_summons_in_dps = Mock(return_value=False)
    app.dps_panel.set_include_summons_in_dps = Mock()
    app.stats_panel = Mock(refresh=Mock())
    app.settings_controller = Mock()
    app.import_controller = Mock(shutdown=Mock())
    app.monitor_controller = Mock(shutdown=Mock())
    app.debug_panel = Mock(log=Mock())
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


def test_show_about_modal_delegates_to_about_dialog(monkeypatch, app_shell) -> None:
    show_about_dialog = Mock()
    monkeypatch.setattr(main_window_module, "show_about_dialog", show_about_dialog)
    app_shell.window_icon_path = "app.ico"

    app_shell.show_about_modal()

    show_about_dialog.assert_called_once_with(app_shell.root, icon_path="app.ico")


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
    app_shell.dps_query_service = Mock(time_tracking_mode="global", include_summons_in_dps=True)
    app_shell.dps_panel.time_tracking_var = Mock()

    app_shell._restore_persisted_dps_panel_state()

    app_shell.dps_panel.time_tracking_var.set.assert_called_once_with("Global")
    app_shell.dps_panel.set_include_summons_in_dps.assert_called_once_with(True)


def test_include_summons_in_dps_toggle_updates_only_dps_and_schedules_save(app_shell) -> None:
    app_shell.dps_panel.get_include_summons_in_dps.return_value = True
    app_shell.dps_query_service = Mock(set_include_summons_in_dps=Mock())
    app_shell._schedule_session_settings_save = Mock()

    app_shell._on_include_summons_changed()

    app_shell.dps_query_service.set_include_summons_in_dps.assert_called_once_with(True)
    app_shell._schedule_session_settings_save.assert_called_once_with()
    app_shell.dps_panel.refresh.assert_called_once_with()
    app_shell.stats_panel.refresh.assert_not_called()


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
            include_summons_in_dps=True,
        ),
    )
    monkeypatch.setattr(main_window_module, "get_default_log_directory", lambda: r"C:\default_logs")
    monkeypatch.setattr(main_window_module.font, "nametofont", lambda _name: Mock())
    monkeypatch.setattr(
        main_window_module.SessionSettingsController,
        "load_initial_settings",
        lambda self: AppSettings(
            log_directory=r"C:\persisted_logs",
            death_fallback_line="Persisted fallback",
            parse_immunity=False,
            first_timestamp_mode="global",
            include_summons_in_dps=True,
        ),
    )
    _patch_init_dependencies(monkeypatch)

    app = WoosNwnParserApp(root)

    assert app.log_directory == r"C:\persisted_logs"
    assert app._initial_death_fallback_line == "Persisted fallback"
    assert app.parser.parse_immunity is False
    assert app.dps_query_service.time_tracking_mode == "global"
    assert app.dps_query_service.include_summons_in_dps is True


def test_init_defaults_parse_immunity_on_when_setting_missing(monkeypatch) -> None:
    root = Mock()
    root.after = Mock()
    root.title = Mock()
    root.geometry = Mock()

    monkeypatch.setattr(main_window_module, "load_app_settings", lambda: AppSettings())
    monkeypatch.setattr(main_window_module, "get_default_log_directory", lambda: r"C:\default_logs")
    monkeypatch.setattr(main_window_module.font, "nametofont", lambda _name: Mock())
    _patch_init_dependencies(monkeypatch)

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
    _patch_init_dependencies(monkeypatch)

    app = WoosNwnParserApp(root)

    assert app.data_queue.maxsize == DEFAULT_APP_RUNTIME_CONFIG.queue.data_queue_maxsize


def test_setup_ui_wires_about_button_after_browse_with_tooltip_and_busy_state(monkeypatch) -> None:
    class FakeVar:
        def __init__(self, value=None, **_kwargs) -> None:
            self.value = value

        def set(self, value) -> None:
            self.value = value

        def get(self):
            return self.value

        def trace(self, *_args, **_kwargs) -> None:
            return None

    class FakeWidget:
        def __init__(self, parent=None, **kwargs) -> None:
            self.parent = parent
            self.kwargs = kwargs
            self.pack_calls = []
            self.grid_calls = []
            self.config_calls = []
            self.bind_calls = []
            self.packed_children = []
            self.gridded_children = []
            self.columnconfigure_calls = []

        def pack(self, *args, **kwargs) -> None:
            self.pack_calls.append((args, kwargs))
            if self.parent is not None and hasattr(self.parent, "packed_children"):
                self.parent.packed_children.append(self)

        def grid(self, *args, **kwargs) -> None:
            self.grid_calls.append((args, kwargs))
            if self.parent is not None and hasattr(self.parent, "gridded_children"):
                self.parent.gridded_children.append(self)

        def columnconfigure(self, index, **kwargs) -> None:
            self.columnconfigure_calls.append((index, kwargs))

        def config(self, **kwargs) -> None:
            self.config_calls.append(kwargs)

        def configure(self, **kwargs) -> None:
            self.config(**kwargs)

        def bind(self, *args, **kwargs) -> None:
            self.bind_calls.append((args, kwargs))

    class FakeNotebook(FakeWidget):
        def __init__(self, parent=None, **kwargs) -> None:
            super().__init__(parent, **kwargs)
            self.add_calls = []

        def add(self, *args, **kwargs) -> None:
            self.add_calls.append((args, kwargs))

    class FakeDpsPanel(FakeWidget):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(args[0] if args else None, **kwargs)
            self.time_tracking_combo = FakeWidget(self)
            self.target_filter_combo = FakeWidget(self)
            self.include_summons_check = FakeWidget(self)

    class FakeStatsPanel(FakeWidget):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(args[0] if args else None, **kwargs)

    class FakeImmunityPanel(FakeWidget):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(args[0] if args else None, **kwargs)
            self.target_combo = FakeWidget(self)

    class FakeDeathSnippetPanel(FakeWidget):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(args[0] if args else None, **kwargs)
            self.set_fallback_death_line = Mock()
            self.configure_identity_callbacks = Mock()
            self.get_character_name = Mock(return_value="")
            self.get_fallback_death_line = Mock(
                return_value=ParserSession.DEFAULT_DEATH_FALLBACK_LINE
            )

    class FakeDebugPanel(FakeWidget):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(args[0] if args else None, **kwargs)
            self.debug_mode_var = FakeVar()

    tooltip_manager = Mock()
    app = WoosNwnParserApp.__new__(WoosNwnParserApp)
    app.root = FakeWidget()
    app.log_directory = ""
    app.runtime_config = DEFAULT_APP_RUNTIME_CONFIG
    app.tooltip_manager = tooltip_manager
    app.data_store = Mock()
    app.dps_query_service = Mock()
    app.target_summary_query_service = Mock()
    app.immunity_query_service = Mock()
    app.parser = Mock()
    app._initial_death_fallback_line = ParserSession.DEFAULT_DEATH_FALLBACK_LINE
    app.show_about_modal = Mock()
    app.browse_directory = Mock()
    app.clear_data = Mock()
    app.load_and_parse_selected_files = Mock()
    app._on_monitoring_switch_toggle = Mock()
    app._restore_persisted_dps_panel_state = Mock()
    app._on_time_tracking_mode_changed = Mock()
    app._on_target_filter_changed = Mock()
    app._on_include_summons_changed = Mock()
    app._on_parse_immunity_changed = Mock()
    app._on_death_character_name_changed = Mock()
    app._on_death_fallback_line_changed = Mock()
    app.on_target_selected = Mock()
    app._on_debug_toggle = Mock()
    app._on_notebook_click = Mock()

    monkeypatch.setattr(main_window_module.tk, "StringVar", FakeVar)
    monkeypatch.setattr(main_window_module.tk, "BooleanVar", FakeVar)
    monkeypatch.setattr(main_window_module.ttk, "Frame", FakeWidget)
    monkeypatch.setattr(main_window_module.ttk, "Label", FakeWidget)
    monkeypatch.setattr(main_window_module.ttk, "Entry", FakeWidget)
    monkeypatch.setattr(main_window_module.ttk, "Button", FakeWidget)
    monkeypatch.setattr(main_window_module.ttk, "Checkbutton", FakeWidget)
    monkeypatch.setattr(main_window_module.ttk, "Notebook", FakeNotebook)
    monkeypatch.setattr(main_window_module, "DPSPanel", FakeDpsPanel)
    monkeypatch.setattr(main_window_module, "TargetStatsPanel", FakeStatsPanel)
    monkeypatch.setattr(main_window_module, "ImmunityPanel", FakeImmunityPanel)
    monkeypatch.setattr(main_window_module, "DeathSnippetPanel", FakeDeathSnippetPanel)
    monkeypatch.setattr(main_window_module, "DebugConsolePanel", FakeDebugPanel)

    app.setup_ui()

    file_frame = app.browse_button.parent
    assert app.browse_button.kwargs["text"] == "Browse"
    assert app.about_button.kwargs["text"] == "?"
    assert app.about_button.kwargs["command"] is app.show_about_modal
    assert file_frame.columnconfigure_calls == [
        (1, {"weight": 3, "minsize": 40}),
        (3, {"weight": 1, "minsize": 20}),
    ]
    assert app.dir_label.grid_calls == [((), {"row": 0, "column": 1, "sticky": "ew", "padx": (2, 2)})]
    assert app.active_file_label.grid_calls == [
        ((), {"row": 0, "column": 3, "sticky": "ew", "padx": 5})
    ]
    assert app.browse_button.grid_calls == [((), {"row": 0, "column": 4, "sticky": "w", "padx": 5})]
    assert app.about_button.grid_calls == [((), {"row": 0, "column": 5, "sticky": "w", "padx": 5})]
    assert file_frame.gridded_children.index(app.about_button) == (
        file_frame.gridded_children.index(app.browse_button) + 1
    )
    tooltip_manager.register.assert_any_call(app.about_button, "About this app")

    app._set_import_ui_busy(True)
    app._set_import_ui_busy(False)

    assert app.about_button.config_calls[-2:] == [
        {"state": tk.DISABLED},
        {"state": tk.NORMAL},
    ]
