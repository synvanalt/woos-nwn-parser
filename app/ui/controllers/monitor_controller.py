"""Live-monitor orchestration for the Tk UI."""

from __future__ import annotations

import queue
import threading
import time

import tkinter as tk
from tkinter import filedialog, ttk

from ...monitor import LogDirectoryMonitor
from ..message_dialogs import show_warning_dialog


class MonitorController:
    """Own monitor lifecycle, background polling, and status labels."""

    def __init__(
        self,
        *,
        root: tk.Misc,
        parser,
        data_queue,
        debug_panel,
        dps_panel,
        get_log_directory,
        set_log_directory,
        set_monitoring_switch_ui,
        set_active_file_name,
        log_debug,
        persist_settings_now,
        get_window_icon_path,
        get_queue_pressure_state,
        get_monitor_max_lines_per_poll,
        get_monitor_sleep_seconds,
    ) -> None:
        self.root = root
        self.parser = parser
        self.data_queue = data_queue
        self.debug_panel = debug_panel
        self.dps_panel = dps_panel
        self.get_log_directory = get_log_directory
        self.set_log_directory = set_log_directory
        self.set_monitoring_switch_ui = set_monitoring_switch_ui
        self._set_active_file_name = set_active_file_name
        self.log_debug = log_debug
        self.persist_settings_now = persist_settings_now
        self.get_window_icon_path = get_window_icon_path
        self.get_queue_pressure_state = get_queue_pressure_state
        self.get_monitor_max_lines_per_poll = get_monitor_max_lines_per_poll
        self.get_monitor_sleep_seconds = get_monitor_sleep_seconds

        self.directory_monitor = None
        self.is_monitoring = False
        self.monitor_thread = None
        self.monitor_stop_event = threading.Event()
        self._monitor_restart_job = None
        self._monitor_active_file_name = "N/A"
        self._monitor_log_queue = queue.SimpleQueue()
        self._debug_monitor_enabled = False
        self.polling_job = None

    @property
    def active_file_name(self) -> str:
        return self._monitor_active_file_name

    def set_debug_enabled(self, enabled: bool) -> None:
        """Update whether monitor-side debug messages should be emitted."""
        self._debug_monitor_enabled = bool(enabled)

    def configure_switch_style(self) -> None:
        """Add monitoring label colors on top of the existing Switch style."""
        style = ttk.Style(self.root)
        try:
            style.layout("Monitoring.Switch.TCheckbutton", style.layout("Switch.TCheckbutton"))
        except tk.TclError:
            pass
        style.map(
            "Monitoring.Switch.TCheckbutton",
            foreground=[
                ("selected", "#56C9FF"),
                ("!selected", "#FF99A4"),
                ("disabled", "#808A93"),
            ],
        )

    def browse_for_directory(self) -> None:
        """Open directory dialog to select a log directory."""
        directory = filedialog.askdirectory(
            title="Select Log Directory (contains nwclientLog*.txt files)",
            parent=self.root,
        )
        if not directory:
            return
        had_log_files = self.select_log_directory(directory)
        if not had_log_files:
            show_warning_dialog(
                self.root,
                "No Log Files",
                "No nwclientLog*.txt files found in this directory.\n"
                "Monitoring will wait for log files to appear.",
                icon_path=self.get_window_icon_path(),
            )

    def select_log_directory(self, directory: str) -> bool:
        """Apply a log directory and refresh active-file state."""
        self.set_log_directory(directory)

        temp_monitor = LogDirectoryMonitor(directory)
        active_file = temp_monitor.find_active_log_file()
        self._monitor_active_file_name = active_file.name if active_file is not None else "N/A"
        self.update_active_file_label()

        if active_file is None:
            self.log_debug("No matching log files found; monitoring will wait for one to appear.", "debug")
        else:
            self.log_debug(f"Selected active log file: {active_file.name}", "debug")

        if self.is_monitoring:
            self.pause()
            self.start()
        else:
            self.set_monitoring_switch_ui(False)

        self.persist_settings_now()
        return active_file is not None

    def start(self) -> None:
        """Start monitoring the configured log directory."""
        if self.is_monitoring:
            return
        log_directory = self.get_log_directory()
        if not log_directory:
            show_warning_dialog(
                self.root,
                "No Directory",
                "Please select a log directory first.",
                icon_path=self.get_window_icon_path(),
            )
            self.set_monitoring_switch_ui(False)
            return

        self.is_monitoring = True
        self.set_monitoring_switch_ui(True)
        self.dps_panel.refresh()

        self.log_debug(f"Starting monitoring of directory: {log_directory}", "debug")
        self.directory_monitor = LogDirectoryMonitor(log_directory)
        self.directory_monitor.start_monitoring()
        current_log_file = getattr(self.directory_monitor, "current_log_file", None)
        self._monitor_active_file_name = current_log_file.name if current_log_file is not None else "N/A"
        self.update_active_file_label()
        self.set_debug_enabled(self.debug_panel.get_debug_enabled())
        started = self.start_monitor_thread()
        if not started:
            self.log_debug(
                "Previous monitor thread is still shutting down; retrying start shortly",
                "warning",
            )
            self.schedule_monitor_restart()
        self.log_debug("Using background monitor thread with bounded line processing", "debug")
        self.poll_ui_tick()
        self.log_debug("Monitoring started successfully", "debug")

    def pause(self) -> None:
        """Pause monitoring and cancel UI poll work."""
        self.is_monitoring = False
        self.set_monitoring_switch_ui(False)
        self.stop_monitor_thread()
        if self._monitor_restart_job is not None:
            self.root.after_cancel(self._monitor_restart_job)
            self._monitor_restart_job = None
        if self.polling_job is not None:
            self.root.after_cancel(self.polling_job)
            self.polling_job = None
        self.log_debug("Monitoring paused", "debug")

    def enqueue_monitor_log(self, message: str, msg_type: str = "debug") -> None:
        """Queue background-monitor log messages for Tk-thread rendering."""
        self._monitor_log_queue.put((str(message), str(msg_type)))

    def drain_monitor_logs(self, max_messages: int = 200) -> None:
        """Flush queued monitor logs on the Tk thread."""
        drained = 0
        while drained < max_messages:
            try:
                message, msg_type = self._monitor_log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_debug(message, msg_type)
            drained += 1

    def start_monitor_thread(self) -> bool:
        """Start background thread that performs file I/O and parsing."""
        thread = self.monitor_thread
        if thread is not None and thread.is_alive():
            return False
        self.monitor_stop_event.clear()
        self.monitor_thread = threading.Thread(
            target=self.monitor_loop,
            name="nwn-log-monitor",
            daemon=True,
        )
        self.monitor_thread.start()
        return True

    def stop_monitor_thread(self) -> None:
        """Signal the monitor thread to stop and join briefly."""
        self.monitor_stop_event.set()
        thread = self.monitor_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        if thread is not None and thread.is_alive():
            self.log_debug("Monitor thread is still shutting down; restart deferred", "warning")
        else:
            self.monitor_thread = None
        self.update_active_file_label()

    def schedule_monitor_restart(self) -> None:
        """Retry deferred monitor startup if shutdown is still in progress."""
        if self._monitor_restart_job is not None:
            return
        self._monitor_restart_job = self.root.after(100, self.retry_monitor_restart)

    def retry_monitor_restart(self) -> None:
        """Attempt a deferred monitor-thread start."""
        self._monitor_restart_job = None
        if not self.is_monitoring:
            return
        if self.start_monitor_thread():
            self.log_debug("Monitor thread restarted after shutdown", "debug")
            return
        self.schedule_monitor_restart()

    def monitor_loop(self) -> None:
        """Worker loop that polls the active log file and parses new lines."""
        current_thread = threading.current_thread()
        try:
            while not self.monitor_stop_event.is_set():
                directory_monitor = self.directory_monitor
                if directory_monitor is None:
                    break
                pressure_state = self.get_queue_pressure_state()
                has_more_pending = False

                if pressure_state != "saturated":
                    try:
                        has_more_pending = directory_monitor.read_new_lines(
                            self.parser,
                            self.data_queue,
                            on_log_message=self.enqueue_monitor_log,
                            debug_enabled=bool(self._debug_monitor_enabled),
                            max_lines_per_poll=self.get_monitor_max_lines_per_poll(pressure_state),
                        )
                    except Exception as exc:
                        self.enqueue_monitor_log(f"I/O Error: {exc}", "error")
                        has_more_pending = False

                sleep_pressure_state = self.get_queue_pressure_state()
                current_file = directory_monitor.current_log_file
                self._monitor_active_file_name = current_file.name if current_file is not None else "N/A"

                if self.monitor_stop_event.is_set():
                    break
                time.sleep(self.get_monitor_sleep_seconds(sleep_pressure_state, has_more_pending))
        finally:
            if self.monitor_thread is current_thread:
                self.monitor_thread = None

    def poll_ui_tick(self) -> None:
        """Lightweight UI tick for monitor status updates."""
        if self.is_monitoring:
            self.drain_monitor_logs()
            self.update_active_file_label()
            self.polling_job = self.root.after(250, self.poll_ui_tick)

    def update_active_file_label(self) -> None:
        """Update the visible active-file label text."""
        self._set_active_file_name(self._monitor_active_file_name or "N/A")

    def shutdown(self) -> None:
        """Stop monitoring during app shutdown."""
        self.pause()
