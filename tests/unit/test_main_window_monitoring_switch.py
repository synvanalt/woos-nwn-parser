"""Unit tests for monitoring switch behavior in the main window."""

import queue
import threading
import tkinter as tk
from tkinter import ttk
from unittest.mock import Mock

import pytest

from app.ui.main_window import WoosNwnParserApp
import app.ui.main_window as main_window_module


def _can_create_tk_root() -> bool:
    """Check if Tk root creation is possible in this environment."""
    try:
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
        return True
    except (tk.TclError, RuntimeError, Exception):
        return False


_TK_AVAILABLE = _can_create_tk_root()


@pytest.fixture
def app_shell(shared_tk_root):
    """Create a minimal WoosNwnParserApp instance for monitoring switch tests."""
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")

    app = WoosNwnParserApp.__new__(WoosNwnParserApp)
    app.root = Mock()
    app.root.after = Mock(return_value="poll-job-id")
    app.root.after_cancel = Mock()

    app.log_directory = r"C:\logs"
    app.is_monitoring = False
    app.polling_job = None
    app.dps_refresh_job = None
    app.directory_monitor = None

    app.parser = Mock()
    app.data_queue = queue.Queue()
    app.data_store = Mock()
    app.data_store.version = 0
    app._last_refresh_version = 0
    app.refresh_targets = Mock()
    app.monitor_thread = None
    app.monitor_stop_event = threading.Event()
    app._monitor_active_file_name = "N/A"
    app._monitor_log_queue = queue.SimpleQueue()
    app._debug_monitor_enabled = False
    app._start_monitor_thread = Mock()
    app._stop_monitor_thread = Mock()
    app._drain_monitor_logs = Mock()

    app.active_file_text = tk.StringVar(master=shared_tk_root, value="N/A")
    app.monitoring_var = tk.BooleanVar(master=shared_tk_root, value=False)
    app.monitoring_text = tk.StringVar(master=shared_tk_root, value="Paused")
    app.monitoring_switch = ttk.Checkbutton(
        shared_tk_root,
        variable=app.monitoring_var,
        textvariable=app.monitoring_text,
        style="Switch.TCheckbutton",
    )

    app.dps_panel = Mock()
    app.debug_panel = Mock()
    app.debug_panel.get_debug_enabled.return_value = False
    app.log_debug = Mock()
    app.window_icon_path = None

    return app


@pytest.mark.skipif(not _TK_AVAILABLE, reason="Tkinter display not available")
class TestMonitoringSwitch:
    """Test suite for monitoring switch text/state and behavior mapping."""

    def test_switch_label_tracks_state(self, app_shell):
        app_shell._set_monitoring_switch_ui(True)
        assert app_shell.monitoring_var.get() is True
        assert app_shell.monitoring_text.get() == "Monitoring"

        app_shell._set_monitoring_switch_ui(False)
        assert app_shell.monitoring_var.get() is False
        assert app_shell.monitoring_text.get() == "Paused"

    def test_toggle_routes_to_start_and_pause(self, app_shell, monkeypatch):
        start_mock = Mock()
        pause_mock = Mock()
        monkeypatch.setattr(app_shell, "start_monitoring", start_mock)
        monkeypatch.setattr(app_shell, "pause_monitoring", pause_mock)

        app_shell.monitoring_var.set(True)
        app_shell._on_monitoring_switch_toggle()
        start_mock.assert_called_once()
        pause_mock.assert_not_called()

        start_mock.reset_mock()
        app_shell.monitoring_var.set(False)
        app_shell._on_monitoring_switch_toggle()
        pause_mock.assert_called_once()
        start_mock.assert_not_called()

    def test_start_monitoring_turns_switch_on_and_starts_polling(self, app_shell, monkeypatch):
        class FakeMonitor:
            def __init__(self, directory):
                self.directory = directory
                self.started = False
                self.current_log_file = None

            def start_monitoring(self):
                self.started = True

            def read_new_lines(self, *args, **kwargs):
                return None

            def get_active_log_file(self):
                return None

        monkeypatch.setattr(main_window_module, "LogDirectoryMonitor", FakeMonitor)

        app_shell.start_monitoring()

        assert app_shell.is_monitoring is True
        assert app_shell.monitoring_var.get() is True
        assert app_shell.monitoring_text.get() == "Monitoring"
        assert app_shell.directory_monitor is not None
        assert app_shell.directory_monitor.started is True
        app_shell.dps_panel.refresh.assert_called_once()
        app_shell._start_monitor_thread.assert_called_once()
        app_shell.root.after.assert_called_once()
        assert app_shell.polling_job == "poll-job-id"
        assert app_shell.active_file_text.get() == "N/A"

    def test_pause_monitoring_turns_switch_off_and_cancels_jobs(self, app_shell):
        app_shell.is_monitoring = True
        app_shell.monitoring_var.set(True)
        app_shell.monitoring_text.set("Monitoring")
        app_shell.polling_job = "poll-job-id"
        app_shell.dps_refresh_job = "dps-job-id"

        app_shell.pause_monitoring()

        assert app_shell.is_monitoring is False
        assert app_shell.monitoring_var.get() is False
        assert app_shell.monitoring_text.get() == "Paused"
        assert app_shell.polling_job is None
        assert app_shell.dps_refresh_job is None
        app_shell._stop_monitor_thread.assert_called_once()
        app_shell.root.after_cancel.assert_any_call("poll-job-id")
        app_shell.root.after_cancel.assert_any_call("dps-job-id")

    def test_start_monitoring_without_directory_reverts_switch_off(self, app_shell, monkeypatch):
        app_shell.log_directory = None
        app_shell.monitoring_var.set(True)
        app_shell.monitoring_text.set("Monitoring")
        showwarning_mock = Mock()
        monkeypatch.setattr(main_window_module, "show_warning_dialog", showwarning_mock)

        app_shell.start_monitoring()

        showwarning_mock.assert_called_once_with(
            app_shell.root,
            "No Directory",
            "Please select a log directory first.",
            icon_path=None,
        )
        assert app_shell.is_monitoring is False
        assert app_shell.monitoring_var.get() is False
        assert app_shell.monitoring_text.get() == "Paused"
        assert app_shell.directory_monitor is None

    def test_start_monitoring_sets_active_filename_from_monitor(self, app_shell, monkeypatch):
        class FakeMonitor:
            def __init__(self, directory):
                self.directory = directory
                self.started = False
                self.current_log_file = main_window_module.Path(r"C:\logs\nwclientLog3.txt")

            def start_monitoring(self):
                self.started = True

            def read_new_lines(self, *args, **kwargs):
                return None

            def get_active_log_file(self):
                return self.current_log_file

        monkeypatch.setattr(main_window_module, "LogDirectoryMonitor", FakeMonitor)

        app_shell.start_monitoring()

        assert app_shell._monitor_active_file_name == "nwclientLog3.txt"
        assert app_shell.active_file_text.get() == "nwclientLog3.txt"
