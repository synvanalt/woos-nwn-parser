"""Additional orchestration tests for WoosNwnParserApp."""

from collections import deque
import queue
import threading
import tkinter as tk
from unittest.mock import Mock

import pytest

import app.ui.main_window as main_window_module
from app.ui.main_window import WoosNwnParserApp
from app.settings import AppSettings


@pytest.fixture
def app_shell(shared_tk_root) -> WoosNwnParserApp:
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")

    app = WoosNwnParserApp.__new__(WoosNwnParserApp)
    app.root = Mock()
    app.root.after = Mock(return_value="after-job-id")
    app.root.after_cancel = Mock()
    app.root.destroy = Mock()

    app.is_monitoring = False
    app.log_directory = r"C:\logs"
    app.polling_job = None
    app.dps_refresh_job = None
    app.directory_monitor = None

    app.dir_text = tk.StringVar(master=shared_tk_root, value="No directory selected")
    app.active_file_text = tk.StringVar(master=shared_tk_root, value="-")
    app.monitoring_var = tk.BooleanVar(master=shared_tk_root, value=False)
    app.monitoring_text = tk.StringVar(master=shared_tk_root, value="Paused")

    app._set_monitoring_switch_ui = Mock()
    app.log_debug = Mock()
    app.refresh_targets = Mock()
    app.update_active_file_label = Mock()

    app.data_store = Mock()
    app.data_store.version = 0
    app._last_refresh_version = 0
    app._dps_dirty = False
    app._targets_dirty = False
    app._immunity_dirty_targets = set()
    app._queue_tick_ms = 50
    app._refresh_job = None
    app.data_queue = queue.Queue()
    app.parser = Mock()
    app.monitor_thread = None
    app.monitor_stop_event = threading.Event()
    app._monitor_active_file_name = "-"
    app._monitor_log_queue = queue.SimpleQueue()
    app._debug_monitor_enabled = False
    app._drain_monitor_logs = Mock()
    app._start_monitor_thread = Mock()
    app._stop_monitor_thread = Mock()

    app.debug_panel = Mock()
    app.debug_panel.get_debug_enabled.return_value = False
    app.dps_panel = Mock()
    app.dps_panel.refresh = Mock()

    app.queue_processor = Mock()

    app._import_status_lock = threading.Lock()
    app._import_status = {}
    app._pending_file_payloads = deque()
    app._is_applying_payload = False
    app._last_modal_file = ""
    app._last_modal_files_completed = -1
    app.is_importing = False
    app.import_poll_job = None
    app.import_status_text = Mock()
    app.import_progress_text = Mock()
    app.import_process = None
    app.import_result_queue = None
    app.import_abort_flag = None
    app.import_abort_event = threading.Event()
    app.import_abort_button = None
    app.import_modal = None

    app.pause_monitoring = Mock()

    return app


def test_browse_directory_warns_when_no_log_files(app_shell, monkeypatch) -> None:
    monkeypatch.setattr(main_window_module.filedialog, "askdirectory", lambda **kwargs: r"C:\new_logs")
    monkeypatch.setattr(main_window_module.Path, "glob", lambda self, pattern: [])
    warning_mock = Mock()
    monkeypatch.setattr(main_window_module.messagebox, "showwarning", warning_mock)

    app_shell.browse_directory()

    assert app_shell.log_directory == r"C:\new_logs"
    assert app_shell.dir_text.get() == r"C:\new_logs"
    warning_mock.assert_called_once()
    app_shell._set_monitoring_switch_ui.assert_called_once_with(app_shell.is_monitoring)


def test_browse_directory_logs_found_files(app_shell, monkeypatch) -> None:
    monkeypatch.setattr(main_window_module.filedialog, "askdirectory", lambda **kwargs: r"C:\new_logs")
    monkeypatch.setattr(main_window_module.Path, "glob", lambda self, pattern: [main_window_module.Path("nwclientLog1.txt")])
    warning_mock = Mock()
    monkeypatch.setattr(main_window_module.messagebox, "showwarning", warning_mock)

    app_shell.browse_directory()

    warning_mock.assert_not_called()
    app_shell.log_debug.assert_called_once()
    assert "Found 1 log file" in app_shell.log_debug.call_args[0][0]


def test_browse_directory_persists_session_settings(app_shell, monkeypatch) -> None:
    monkeypatch.setattr(main_window_module.filedialog, "askdirectory", lambda **kwargs: r"C:\saved_logs")
    monkeypatch.setattr(main_window_module.Path, "glob", lambda self, pattern: [main_window_module.Path("nwclientLog1.txt")])
    app_shell._persist_session_settings = Mock()

    app_shell.browse_directory()

    app_shell._persist_session_settings.assert_called_once()


def test_poll_log_file_runs_ui_tick_when_monitoring(app_shell) -> None:
    app_shell.is_monitoring = True
    app_shell.directory_monitor = object()

    app_shell.poll_log_file()

    app_shell._drain_monitor_logs.assert_called_once()
    app_shell.update_active_file_label.assert_called_once()
    app_shell.root.after.assert_called_once_with(250, app_shell.poll_log_file)
    assert app_shell.polling_job == "after-job-id"


def test_poll_log_file_skips_when_not_monitoring(app_shell) -> None:
    app_shell.is_monitoring = False
    app_shell.directory_monitor = object()

    app_shell.poll_log_file()

    app_shell._drain_monitor_logs.assert_not_called()
    app_shell.update_active_file_label.assert_not_called()
    app_shell.root.after.assert_not_called()


def test_poll_log_file_handles_missing_monitor(app_shell) -> None:
    app_shell.is_monitoring = True
    app_shell.directory_monitor = None

    app_shell.poll_log_file()

    app_shell._drain_monitor_logs.assert_called_once()
    app_shell.update_active_file_label.assert_called_once()
    app_shell.root.after.assert_called_once_with(250, app_shell.poll_log_file)


def test_poll_import_progress_schedules_when_worker_not_done(app_shell) -> None:
    app_shell.is_importing = True
    app_shell._drain_import_events = Mock()
    app_shell._finalize_import = Mock()
    app_shell._import_status = {
        "worker_done": False,
        "current_file": "log1.txt",
        "files_completed": 1,
        "total_files": 3,
    }

    app_shell._poll_import_progress()

    app_shell._drain_import_events.assert_called_once()
    app_shell.import_status_text.set.assert_called_once_with("Parsing: log1.txt")
    app_shell.import_progress_text.set.assert_called_once_with("1/3 files completed")
    app_shell._finalize_import.assert_not_called()
    assert app_shell.import_poll_job == "after-job-id"


def test_poll_import_progress_finalizes_when_done_and_no_pending_payloads(app_shell) -> None:
    app_shell.is_importing = True
    app_shell._drain_import_events = Mock()
    app_shell._finalize_import = Mock()
    app_shell._import_status = {
        "worker_done": True,
        "current_file": "log2.txt",
        "files_completed": 2,
        "total_files": 2,
    }
    app_shell._pending_file_payloads.clear()
    app_shell._is_applying_payload = False

    app_shell._poll_import_progress()

    app_shell._finalize_import.assert_called_once()


def test_finalize_import_error_path_shows_warning(app_shell, monkeypatch) -> None:
    warning_mock = Mock()
    monkeypatch.setattr(main_window_module.messagebox, "showwarning", warning_mock)

    app_shell.is_importing = True
    app_shell._set_import_ui_busy = Mock()
    app_shell.refresh_targets = Mock()
    app_shell.dps_panel = Mock(refresh=Mock())
    app_shell._import_status = {
        "errors": ["bad file"],
        "aborted": False,
        "files_completed": 0,
        "total_files": 1,
    }

    app_shell._finalize_import()

    warning_mock.assert_called_once()
    app_shell.log_debug.assert_called_once_with(
        "Load & Parse completed with file errors.",
        msg_type="warning",
    )


def test_process_queue_wires_callbacks_and_reschedules(app_shell) -> None:
    app_shell.process_queue()

    app_shell.queue_processor.process_queue.assert_called_once()
    kwargs = app_shell.queue_processor.process_queue.call_args.kwargs
    assert kwargs["on_log_message"] == app_shell.log_debug
    assert kwargs["on_dps_updated"] == app_shell.refresh_dps
    assert kwargs["on_target_selected"] == app_shell._on_target_details_needed
    assert kwargs["on_immunity_changed"] == app_shell._on_immunity_changed
    assert kwargs["on_damage_dealt"] == app_shell._on_damage_dealt
    assert kwargs["on_death_snippet"] == app_shell._on_death_snippet
    assert kwargs["on_character_identified"] == app_shell._on_death_character_identified
    app_shell.root.after.assert_called_with(50, app_shell.process_queue)


def test_process_queue_reschedules_aggressively_under_pressure(app_shell) -> None:
    app_shell.root.after.reset_mock()
    app_shell.queue_processor.process_queue.return_value = Mock(
        dps_updated=False,
        death_events=[],
        character_identity_events=[],
        targets_to_refresh=set(),
        immunity_targets=set(),
        damage_targets=set(),
        pressure_state="saturated",
    )

    app_shell.process_queue()

    app_shell.root.after.assert_called_with(1, app_shell.process_queue)


def test_on_closing_terminates_active_import_process(app_shell) -> None:
    app_shell.is_importing = True
    app_shell.import_abort_event = threading.Event()
    app_shell.import_abort_flag = Mock()
    app_shell.import_abort_flag.set = Mock()
    app_shell.import_process = Mock()
    app_shell.import_process.is_alive.return_value = True
    app_shell._flush_pending_session_settings_save = Mock()
    app_shell.data_store = Mock()
    app_shell.pause_monitoring = Mock()

    app_shell.on_closing()

    app_shell._flush_pending_session_settings_save.assert_called_once()
    assert app_shell.import_abort_event.is_set() is True
    app_shell.import_abort_flag.set.assert_called_once()
    app_shell.import_process.terminate.assert_called_once()
    app_shell.pause_monitoring.assert_called_once()
    app_shell.data_store.close.assert_called_once()
    app_shell.root.destroy.assert_called_once()


def test_init_uses_persisted_settings_over_defaults(monkeypatch) -> None:
    root = Mock()
    root.after = Mock()
    root.title = Mock()
    root.geometry = Mock()

    monkeypatch.setattr(main_window_module, "load_app_settings", lambda: AppSettings(
        log_directory=r"C:\persisted_logs",
        death_fallback_line="Persisted fallback",
    ))
    monkeypatch.setattr(main_window_module, "get_default_log_directory", lambda: r"C:\default_logs")
    monkeypatch.setattr(main_window_module.font, "nametofont", lambda _name: Mock())
    monkeypatch.setattr(WoosNwnParserApp, "setup_ui", lambda self: None)
    monkeypatch.setattr(WoosNwnParserApp, "process_queue", lambda self: None)
    monkeypatch.setattr(WoosNwnParserApp, "_set_monitoring_switch_ui", lambda self, _value: None)

    app = WoosNwnParserApp(root)

    assert app.log_directory == r"C:\persisted_logs"
    assert app._initial_death_fallback_line == "Persisted fallback"


def test_time_tracking_mode_change_refreshes_when_not_monitoring(app_shell) -> None:
    app_shell.is_monitoring = False
    app_shell.dps_service = Mock()
    app_shell.dps_service.time_tracking_mode = "per_character"
    app_shell.dps_panel.time_tracking_var = Mock()
    app_shell.dps_panel.time_tracking_var.get.return_value = "Global"

    event = Mock()
    event.widget = Mock()

    app_shell._on_time_tracking_mode_changed(event)

    event.widget.selection_clear.assert_called_once()
    app_shell.dps_service.set_time_tracking_mode.assert_called_once_with("global")
    app_shell.dps_panel.refresh.assert_called_once()


def test_time_tracking_mode_change_noop_when_mode_unchanged(app_shell) -> None:
    app_shell.dps_service = Mock()
    app_shell.dps_service.time_tracking_mode = "global"
    app_shell.dps_panel.time_tracking_var = Mock()
    app_shell.dps_panel.time_tracking_var.get.return_value = "Global"

    event = Mock()
    event.widget = Mock()

    app_shell._on_time_tracking_mode_changed(event)

    event.widget.selection_clear.assert_called_once()
    app_shell.dps_service.set_time_tracking_mode.assert_not_called()
    app_shell.dps_panel.refresh.assert_not_called()


def test_time_tracking_mode_change_refreshes_when_monitoring(app_shell) -> None:
    app_shell.is_monitoring = True
    app_shell.dps_service = Mock()
    app_shell.dps_service.time_tracking_mode = "global"
    app_shell.dps_panel.time_tracking_var = Mock()
    app_shell.dps_panel.time_tracking_var.get.return_value = "Per Character"

    event = Mock()
    event.widget = Mock()

    app_shell._on_time_tracking_mode_changed(event)

    event.widget.selection_clear.assert_called_once()
    app_shell.dps_service.set_time_tracking_mode.assert_called_once_with("per_character")
    app_shell.dps_panel.refresh.assert_called_once()
