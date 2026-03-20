"""Unit tests for monitor-controller switch behavior."""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from unittest.mock import Mock

import app.ui.controllers.monitor_controller as monitor_module
from app.ui.controllers.monitor_controller import MonitorController


def _make_controller(log_directory: str | None = r"C:\logs") -> tuple[MonitorController, Mock]:
    root = Mock()
    root.after = Mock(return_value="poll-job-id")
    root.after_cancel = Mock()

    active_file_names: list[str] = []
    switch_states: list[bool] = []

    controller = MonitorController(
        root=root,
        parser=Mock(),
        data_queue=queue.Queue(),
        debug_panel=Mock(get_debug_enabled=Mock(return_value=False)),
        dps_panel=Mock(refresh=Mock()),
        get_log_directory=lambda: log_directory,
        set_log_directory=Mock(),
        set_monitoring_switch_ui=lambda is_on: switch_states.append(is_on),
        set_active_file_name=lambda file_name: active_file_names.append(file_name),
        log_debug=Mock(),
        persist_settings_now=Mock(),
        get_window_icon_path=lambda: None,
        get_queue_pressure_state=lambda: "normal",
        get_monitor_max_lines_per_poll=lambda _pressure_state: 2000,
        get_monitor_sleep_seconds=lambda _pressure_state, _has_more_pending: 0.05,
    )
    controller._captured_switch_states = switch_states
    controller._captured_active_file_names = active_file_names
    return controller, root


class TestMonitoringSwitch:
    def test_start_monitoring_turns_switch_on_and_starts_polling(self, monkeypatch) -> None:
        class FakeMonitor:
            def __init__(self, directory):
                self.directory = directory
                self.started = False
                self.current_log_file = None

            def start_monitoring(self):
                self.started = True

            def read_new_lines(self, *args, **kwargs):
                return False

        monkeypatch.setattr(monitor_module, "LogDirectoryMonitor", FakeMonitor)
        controller, root = _make_controller()
        controller.start_monitor_thread = Mock(return_value=True)

        controller.start()

        assert controller.is_monitoring is True
        assert controller.directory_monitor is not None
        assert controller.directory_monitor.started is True
        assert controller._captured_switch_states[-1] is True
        assert controller.dps_panel.refresh.call_count == 1
        controller.start_monitor_thread.assert_called_once_with()
        root.after.assert_called_once_with(250, controller.poll_ui_tick)
        assert controller.polling_job == "poll-job-id"
        assert controller._captured_active_file_names[-1] == "N/A"

    def test_pause_monitoring_turns_switch_off_and_cancels_jobs(self) -> None:
        controller, root = _make_controller()
        controller.is_monitoring = True
        controller.polling_job = "poll-job-id"
        controller._monitor_restart_job = "restart-job-id"
        controller.stop_monitor_thread = Mock()

        controller.pause()

        assert controller.is_monitoring is False
        assert controller._captured_switch_states[-1] is False
        controller.stop_monitor_thread.assert_called_once_with()
        root.after_cancel.assert_any_call("poll-job-id")
        root.after_cancel.assert_any_call("restart-job-id")
        assert controller.polling_job is None
        assert controller._monitor_restart_job is None

    def test_stop_monitor_thread_preserves_last_known_active_filename(self) -> None:
        controller, _root = _make_controller()
        controller._monitor_active_file_name = "nwclientLog2.txt"
        controller.monitor_thread = None

        controller.stop_monitor_thread()

        assert controller._monitor_active_file_name == "nwclientLog2.txt"
        assert controller._captured_active_file_names[-1] == "nwclientLog2.txt"

    def test_start_monitoring_without_directory_reverts_switch_off(self, monkeypatch) -> None:
        warning_mock = Mock()
        monkeypatch.setattr(monitor_module, "show_warning_dialog", warning_mock)
        controller, _root = _make_controller(log_directory=None)

        controller.start()

        warning_mock.assert_called_once_with(
            controller.root,
            "No Directory",
            "Please select a log directory first.",
            icon_path=None,
        )
        assert controller.is_monitoring is False
        assert controller._captured_switch_states[-1] is False
        assert controller.directory_monitor is None

    def test_start_monitoring_sets_active_filename_from_monitor(self, monkeypatch) -> None:
        class FakeMonitor:
            def __init__(self, directory):
                self.directory = directory
                self.current_log_file = Path(r"C:\logs\nwclientLog3.txt")

            def start_monitoring(self):
                return None

            def read_new_lines(self, *args, **kwargs):
                return False

        monkeypatch.setattr(monitor_module, "LogDirectoryMonitor", FakeMonitor)
        controller, _root = _make_controller()
        controller.start_monitor_thread = Mock(return_value=True)

        controller.start()

        assert controller._monitor_active_file_name == "nwclientLog3.txt"
        assert controller._captured_active_file_names[-1] == "nwclientLog3.txt"

    def test_start_monitoring_defers_when_previous_thread_is_alive(self, monkeypatch) -> None:
        monkeypatch.setattr(monitor_module, "LogDirectoryMonitor", lambda _directory: Mock(
            start_monitoring=Mock(),
            current_log_file=None,
        ))
        controller, root = _make_controller()
        controller.start_monitor_thread = Mock(return_value=False)
        controller.schedule_monitor_restart = Mock()

        controller.start()

        controller.schedule_monitor_restart.assert_called_once_with()
        assert controller.is_monitoring is True
        root.after.assert_called_once_with(250, controller.poll_ui_tick)

    def test_retry_monitor_restart_waits_for_shutdown_completion(self) -> None:
        controller, root = _make_controller()
        controller.is_monitoring = True
        controller.start_monitor_thread = Mock(side_effect=[False, True])

        controller.schedule_monitor_restart()
        assert controller._monitor_restart_job == "poll-job-id"

        controller.retry_monitor_restart()
        assert controller.start_monitor_thread.call_count == 1

        controller.retry_monitor_restart()
        assert controller.start_monitor_thread.call_count == 2
        assert root.after.call_count == 2

    def test_stop_monitor_thread_joins_live_thread(self) -> None:
        controller, _root = _make_controller()

        thread = Mock(spec=threading.Thread)
        thread.is_alive.side_effect = [True, False]
        controller.monitor_thread = thread

        controller.stop_monitor_thread()

        thread.join.assert_called_once_with(timeout=1.0)
        assert controller.monitor_thread is None
