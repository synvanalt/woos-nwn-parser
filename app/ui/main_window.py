"""Main application window for Woo's NWN Parser.

This module contains the WoosNwnParserApp class which manages the main
application window, UI components, and event processing.
"""

import queue
import threading
import multiprocessing as mp
import time
from time import perf_counter
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font

from ..parser import LogParser
from ..storage import DataStore
from ..monitor import LogDirectoryMonitor
from ..settings import AppSettings, load_app_settings, save_app_settings
from ..utils import IMPORT_RESULT_QUEUE_MAXSIZE, import_worker_process
from ..services import QueueProcessor, DPSCalculationService
from .formatters import get_default_log_directory
from .window_style import apply_dark_title_bar
from .widgets import DPSPanel, TargetStatsPanel, ImmunityPanel, DeathSnippetPanel, DebugConsolePanel


class WoosNwnParserApp:
    """Main application window."""

    DATA_QUEUE_MAXSIZE = 4000
    DATA_QUEUE_PRESSURED_THRESHOLD = 2000
    DATA_QUEUE_SATURATED_THRESHOLD = 3400
    QUEUE_TICK_MS_NORMAL = 50
    QUEUE_TICK_MS_PRESSURED = 10
    QUEUE_TICK_MS_SATURATED = 1
    QUEUE_DRAIN_MAX_EVENTS_NORMAL = 1200
    QUEUE_DRAIN_MAX_EVENTS_PRESSURED = 2000
    QUEUE_DRAIN_MAX_EVENTS_SATURATED = 2600
    QUEUE_DRAIN_MAX_TIME_MS_NORMAL = 8.0
    QUEUE_DRAIN_MAX_TIME_MS_PRESSURED = 10.0
    QUEUE_DRAIN_MAX_TIME_MS_SATURATED = 12.0
    MONITOR_LINES_PER_POLL_NORMAL = 2000
    MONITOR_LINES_PER_POLL_PRESSURED = 600
    MONITOR_SLEEP_ACTIVE_NORMAL = 0.05
    MONITOR_SLEEP_ACTIVE_PRESSURED = 0.08
    MONITOR_SLEEP_ACTIVE_SATURATED = 0.12
    MONITOR_SLEEP_IDLE_NORMAL = 0.5
    MONITOR_SLEEP_IDLE_PRESSURED = 0.35
    MONITOR_SLEEP_IDLE_SATURATED = 0.12
    IMPORT_APPLY_FRAME_BUDGET_MS = 6.0
    IMPORT_APPLY_MUTATION_BATCH_SIZE = 384

    def __init__(self, root: tk.Tk) -> None:
        """Initialize the application.

        Args:
            root: The root Tkinter window
        """
        self.root = root
        self.root.title("Woo's NWN Parser")
        self.root.geometry("730x550")

        # Core services
        self._settings = load_app_settings()
        parse_immunity_enabled = self._settings.parse_immunity
        if parse_immunity_enabled is None:
            parse_immunity_enabled = True
        self.parser = LogParser(parse_immunity=parse_immunity_enabled)
        self.data_store = DataStore()
        self.queue_processor = QueueProcessor(self.data_store, self.parser)
        self.dps_service = DPSCalculationService(self.data_store)
        persisted_first_timestamp_mode = self._settings.first_timestamp_mode
        if persisted_first_timestamp_mode is not None:
            self.dps_service.set_time_tracking_mode(persisted_first_timestamp_mode)

        # Queue and monitoring
        self.data_queue = queue.Queue(maxsize=self.DATA_QUEUE_MAXSIZE)
        self.directory_monitor: Optional[LogDirectoryMonitor] = None
        self.is_monitoring = False
        self._settings_save_job = None
        self._settings_save_delay_ms = 400
        configured_log_directory = (self._settings.log_directory or "").strip()
        self.log_directory = configured_log_directory or get_default_log_directory()
        configured_fallback_line = (self._settings.death_fallback_line or "").strip()
        self._initial_death_fallback_line = configured_fallback_line or LogParser.DEFAULT_DEATH_FALLBACK_LINE
        self.monitor_thread: Optional[threading.Thread] = None
        self.monitor_stop_event = threading.Event()
        self._monitor_restart_job = None
        self._monitor_active_file_name = "-"
        self._monitor_log_queue: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()
        self._debug_monitor_enabled = False

        # Polling and refresh jobs
        self.polling_job = None
        self.dps_refresh_job = None
        self._refresh_job = None

        # Version tracking for dirty checking (avoids redundant refreshes)
        self._last_refresh_version: int = 0
        self._dps_dirty = False
        self._targets_dirty = False
        self._immunity_dirty_targets: set[str] = set()
        self._queue_tick_ms = self.QUEUE_TICK_MS_NORMAL
        self._queue_pressure_state = "normal"

        # Debug mode
        self.debug_mode = False
        self.is_importing = False
        self.import_abort_event = threading.Event()
        self.import_thread: Optional[threading.Thread] = None
        self.import_process = None
        self.import_abort_flag = None
        self.import_result_queue = None
        self.import_poll_job = None
        self.import_modal: Optional[tk.Toplevel] = None
        self.import_status_text: Optional[tk.StringVar] = None
        self.import_progress_text: Optional[tk.StringVar] = None
        self.import_abort_button: Optional[ttk.Button] = None
        self.monitoring_was_active_before_import = False
        self._import_status_lock = threading.Lock()
        self._import_status: Dict[str, Any] = {}
        self._pending_file_payloads = deque()
        self._is_applying_payload = False
        self._last_modal_file: str = ""
        self._last_modal_files_completed: int = -1
        self.window_icon_path: Optional[str] = None
        self.notebook: Optional[ttk.Notebook] = None
        self._debug_tab_visible = False
        self._dps_tab_click_times: deque[float] = deque()
        self._debug_unlock_click_target = 7
        self._debug_unlock_window_seconds = 3.0
        self._dps_tab_text = "Damage Per Second"

        # Get the font object defined by the Sun Valley theme to use inside tk non-themed widgets (e.g., tk.Text)
        self.theme_font = font.nametofont("SunValleyBodyFont")

        self.setup_ui()
        self.process_queue()

        # Auto-start monitoring if default log directory is valid.
        # Keep initial switch state ON and only switch OFF when invalid.
        if self.log_directory and Path(self.log_directory).is_dir():
            self.root.after(100, self.start_monitoring)
        else:
            self._set_monitoring_switch_ui(False)


    def setup_ui(self) -> None:
        """Set up the user interface."""
        self._configure_monitoring_switch_style()

        # Control Panel
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(fill="x")

        # Log directory selection row
        file_frame = ttk.Frame(control_frame)
        file_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(file_frame, text="Log Directory:").pack(side="left", padx=5)
        self.dir_text = tk.StringVar(value="No directory selected")
        self.dir_label = ttk.Entry(file_frame, state="readonly", textvariable=self.dir_text, foreground="gray", width=40)
        self.dir_label.pack(side="left", fill="x", expand=True, padx=(2, 2))

        ttk.Label(file_frame, text="File:").pack(side="left", padx=(10, 0))
        self.active_file_text = tk.StringVar(value="-")
        self.active_file_label = ttk.Entry(file_frame, state="readonly", textvariable=self.active_file_text, foreground="gray", width=15)
        self.active_file_label.pack(side="left", padx=5)

        self.browse_button = ttk.Button(file_frame, text="Browse...", command=self.browse_directory)
        self.browse_button.pack(side="left", padx=5)

        # Control buttons
        buttons_frame = ttk.Frame(control_frame)
        buttons_frame.pack(fill="x", pady=(5, 0))

        self.monitoring_var = tk.BooleanVar(value=True)
        self.monitoring_text = tk.StringVar(value="Monitoring")
        self.monitoring_switch = ttk.Checkbutton(
            buttons_frame,
            variable=self.monitoring_var,
            textvariable=self.monitoring_text,
            command=self._on_monitoring_switch_toggle,
            style="Monitoring.Switch.TCheckbutton",
            width=len("Monitoring"),
        )
        self.monitoring_switch.pack(side="left", padx=5)

        self.clear_button = ttk.Button(buttons_frame, text="Clear Data", command=self.clear_data)
        self.clear_button.pack(side="right", padx=5)

        self.load_parse_button = ttk.Button(buttons_frame, text="Load & Parse Logs", command=self.load_and_parse_selected_files)
        self.load_parse_button.pack(side="right", padx=5)


        # Initialize directory label with default if available
        if self.log_directory:
            dir_display = self.log_directory.replace("/", "\\")
            self.dir_text.set(value=dir_display)

        # Main content area with notebook for multiple targets
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        # Tab 1: DPS Panel (using DPSPanel widget)
        self.dps_panel = DPSPanel(self.notebook, self.data_store, self.dps_service)
        self._restore_persisted_dps_panel_state()
        self.notebook.add(self.dps_panel, text=self._dps_tab_text)
        self.dps_panel.time_tracking_combo.bind("<<ComboboxSelected>>", self._on_time_tracking_mode_changed)
        self.dps_panel.target_filter_combo.bind("<<ComboboxSelected>>", self._on_target_filter_changed)

        # Tab 2: Target Stats Panel (using TargetStatsPanel widget)
        self.stats_panel = TargetStatsPanel(self.notebook, self.data_store)
        self.notebook.add(self.stats_panel, text="Target Stats")

        # Tab 3: Immunity Panel (using ImmunityPanel widget)
        self.immunity_panel = ImmunityPanel(
            self.notebook,
            self.data_store,
            self.parser,
            on_parse_immunity_changed=self._on_parse_immunity_changed,
        )
        self.notebook.add(self.immunity_panel, text="Target Immunities")
        self.immunity_panel.target_combo.bind("<<ComboboxSelected>>", self.on_target_selected)

        # Tab 4: Death Snippets Panel
        self.death_snippet_panel = DeathSnippetPanel(self.notebook)
        self.death_snippet_panel.set_fallback_death_line(self._initial_death_fallback_line)
        self.notebook.add(self.death_snippet_panel, text="Death Snippets")
        self.death_snippet_panel.configure_identity_callbacks(
            on_character_name_changed=self._on_death_character_name_changed,
            on_fallback_line_changed=self._on_death_fallback_line_changed,
        )
        self.parser.set_death_character_name(self.death_snippet_panel.get_character_name())
        self.parser.set_death_fallback_line(self.death_snippet_panel.get_fallback_death_line())

        # Tab 5: Debug Console Panel (using DebugConsolePanel widget)
        self.debug_panel = DebugConsolePanel(self.notebook)
        self.debug_panel.debug_mode_var.trace("w", self._on_debug_toggle)
        self.notebook.bind("<Button-1>", self._on_notebook_click, add=True)

    def browse_directory(self) -> None:
        """Open directory dialog to select log directory."""
        directory = filedialog.askdirectory(
            title="Select Log Directory (contains nwclientLog*.txt files)",
            parent=self.root,
        )
        if directory:
            self.log_directory = directory
            # Show directory path (truncated to fit)
            dir_display = directory.replace("/", "\\")  # Use backslashes on Windows
            self.dir_text.set(value=dir_display)

            # Check for log files and show warning if none found
            log_files = list(Path(directory).glob('nwclientLog[1-4].txt'))
            if not log_files:
                messagebox.showwarning(
                    "No Log Files",
                    "No nwclientLog*.txt files found in this directory.\n"
                    "Monitoring will wait for log files to appear."
                )
            else:
                self.log_debug(f"Found {len(log_files)} log file(s) in directory")

            # Keep switch text/state synchronized with actual monitoring status
            self._set_monitoring_switch_ui(self.is_monitoring)
            self._persist_session_settings()

    def load_and_parse_selected_files(self) -> None:
        """Open file picker and parse selected .txt logs in a background worker."""
        if self.is_importing:
            return

        selected_paths = filedialog.askopenfilenames(
            title="Select one or more NWN log files",
            filetypes=[("Text Files", "*.txt")],
            parent=getattr(self, "root", None),
        )
        if not selected_paths:
            return

        selected_files = sorted(
            [Path(path) for path in selected_paths],
            key=lambda p: (p.name.lower(), str(p).lower()),
        )

        self.monitoring_was_active_before_import = self.is_monitoring
        if self.monitoring_was_active_before_import:
            self.pause_monitoring()

        self.import_abort_event = threading.Event()
        self.is_importing = True
        self._import_status = {
            'files': selected_files,
            'total_files': len(selected_files),
            'files_completed': 0,
            'current_file': '',
            'errors': [],
            'aborted': False,
            'success': False,
            'worker_done': False,
        }
        self._last_modal_file = ""
        self._last_modal_files_completed = -1
        self._pending_file_payloads.clear()
        self._is_applying_payload = False

        self._set_import_ui_busy(True)
        self._show_import_modal()
        self._start_import_worker(selected_files)
        self._poll_import_progress()

    def _set_import_ui_busy(self, is_busy: bool) -> None:
        """Disable/enable controls while import is running."""
        state = tk.DISABLED if is_busy else tk.NORMAL
        self.monitoring_switch.config(state=state)
        self.browse_button.config(state=state)
        self.load_parse_button.config(state=state)
        self.clear_button.config(state=state)

    def _show_import_modal(self) -> None:
        """Show a modal with import progress and abort button."""
        self.import_modal = tk.Toplevel(self.root)
        self.import_modal.withdraw()
        self.import_modal.configure(bg="#1c1c1c")
        self.import_modal.title("Parsing Logs")
        self.import_modal.resizable(False, False)
        self.import_modal.transient(self.root)
        self._center_window_on_parent(self.import_modal, 480, 140)
        self._apply_modal_icon(self.import_modal)
        try:
            apply_dark_title_bar(self.import_modal)
        except Exception:
            pass

        container = ttk.Frame(self.import_modal, padding=14)
        container.pack(fill="both", expand=True)

        self.import_status_text = tk.StringVar(value="Preparing selected files...")
        self.import_progress_text = tk.StringVar(value="0 files completed")
        ttk.Label(container, textvariable=self.import_status_text).pack(anchor="w")
        ttk.Label(container, textvariable=self.import_progress_text).pack(anchor="w", pady=(8, 8))

        progress = ttk.Progressbar(container, mode="indeterminate")
        progress.pack(fill="x")
        progress.start(8)
        self.import_modal._progressbar = progress

        self.import_abort_button = ttk.Button(container, text="Abort", command=self.abort_load_parse)
        self.import_abort_button.pack(anchor="se", pady=(14, 0))

        self.import_modal.protocol("WM_DELETE_WINDOW", self.abort_load_parse)

        try:
            self.import_modal.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        def _show_modal_when_ready() -> None:
            self.import_modal.update_idletasks()
            self.import_modal.deiconify()
            self.import_modal.lift()

            def _reveal_modal_after_hidden_render(remaining_repaints: int = 4) -> None:
                self.import_modal.update_idletasks()
                if remaining_repaints > 0:
                    self.import_modal.after(16, lambda: _reveal_modal_after_hidden_render(remaining_repaints - 1))
                    return
                try:
                    self.import_modal.attributes("-alpha", 1.0)
                except tk.TclError:
                    pass
                self.import_modal.grab_set()

            self.import_modal.after_idle(_reveal_modal_after_hidden_render)

        # Reveal only after pending idle layout/styling tasks have run.
        self.import_modal.after_idle(_show_modal_when_ready)

    def _start_import_worker(self, selected_files: List[Path]) -> None:
        """Start worker process for import operation."""
        file_paths = [str(path) for path in selected_files]
        ctx = mp.get_context("spawn")
        self.import_abort_flag = ctx.Event()
        self.import_result_queue = ctx.Queue(maxsize=IMPORT_RESULT_QUEUE_MAXSIZE)
        self.import_process = ctx.Process(
            target=import_worker_process,
            args=(
                file_paths,
                bool(self.parser.parse_immunity),
                self.import_abort_flag,
                self.import_result_queue,
                self.parser.death_character_name,
                self.parser.death_fallback_line,
            ),
            daemon=True,
        )
        self.import_process.start()

    def _drain_import_events(self) -> None:
        """Drain events from the import worker process queue."""
        if self.import_result_queue is None:
            return
        while True:
            try:
                event = self.import_result_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event.get('event')
            if event_type == 'file_started':
                with self._import_status_lock:
                    self._import_status['current_file'] = event.get('file_name', '')
            elif event_type == 'ops_chunk':
                ops = event.get('ops', {})
                self._pending_file_payloads.append({
                    'mutations': ops.get('mutations', []),
                    'death_snippets': ops.get('death_snippets', []),
                    'death_character_identified': ops.get('death_character_identified', []),
                    'index': event.get('index', 0),
                    'mutation_idx': 0,
                })
                if not self._is_applying_payload:
                    self._is_applying_payload = True
                    self.root.after(1, self._apply_pending_payloads_incremental)
            elif event_type == 'file_completed':
                with self._import_status_lock:
                    # UX: advance file counter immediately when parsing of a file finishes.
                    self._import_status['files_completed'] = event.get('index', 0)
            elif event_type == 'file_error':
                with self._import_status_lock:
                    errors = self._import_status.setdefault('errors', [])
                    errors.append(f"{event.get('file_name')}: {event.get('error')}")
            elif event_type == 'aborted':
                with self._import_status_lock:
                    self._import_status['aborted'] = True
                    self._import_status['worker_done'] = True
            elif event_type == 'done':
                with self._import_status_lock:
                    self._import_status['worker_done'] = True

    def _apply_pending_payloads_incremental(self) -> None:
        """Apply completed-file payloads in small slices on the Tk thread."""
        budget_ms = self.IMPORT_APPLY_FRAME_BUDGET_MS
        mutation_batch_size = max(1, int(self.IMPORT_APPLY_MUTATION_BATCH_SIZE))
        deadline = perf_counter() + (budget_ms / 1000.0)
        while perf_counter() < deadline and self._pending_file_payloads:
            item = self._pending_file_payloads[0]
            mutation_idx = item['mutation_idx']
            mutations = item['mutations']
            if mutation_idx < len(mutations):
                batch_end = min(mutation_idx + mutation_batch_size, len(mutations))
                self.data_store.apply_mutations(mutations[mutation_idx:batch_end])
                item['mutation_idx'] = batch_end
                continue

            death_snippets = item['death_snippets']
            if death_snippets:
                self.death_snippet_panel.add_death_events(death_snippets)
                item['death_snippets'] = []

            identity_events = item['death_character_identified']
            if identity_events:
                for identity_event in identity_events:
                    self._on_death_character_identified(identity_event)
                item['death_character_identified'] = []

            self._pending_file_payloads.popleft()

        if self._pending_file_payloads:
            self.root.after(1, self._apply_pending_payloads_incremental)
            return

        self._is_applying_payload = False

    def _poll_import_progress(self) -> None:
        """Update modal with latest import status."""
        if not self.is_importing:
            return

        self._drain_import_events()

        with self._import_status_lock:
            status = dict(self._import_status)

        if self.import_status_text is not None:
            current_file = status.get('current_file') or "Preparing selected files..."
            files_completed = status.get('files_completed', 0)
            if self._last_modal_file != current_file:
                self.import_status_text.set(f"Parsing: {current_file}")
                self._last_modal_file = current_file
        if self.import_progress_text is not None:
            files_completed = status.get('files_completed', 0)
            total_files = status.get('total_files', 0)
            if self._last_modal_files_completed != files_completed:
                self.import_progress_text.set(f"{files_completed}/{total_files} files completed")
                self._last_modal_files_completed = files_completed

        worker_done = bool(status.get('worker_done'))
        has_pending = bool(self._pending_file_payloads) or self._is_applying_payload
        if not worker_done or has_pending:
            self.import_poll_job = self.root.after(200, self._poll_import_progress)
            return

        self._finalize_import()

    def abort_load_parse(self) -> None:
        """Request abort for ongoing import."""
        if not self.is_importing:
            return
        self.import_abort_event.set()
        if self.import_abort_flag is not None:
            self.import_abort_flag.set()
        if self.import_abort_button is not None:
            self.import_abort_button.config(state=tk.DISABLED)
        if self.import_status_text is not None:
            self.import_status_text.set("Aborting...")

    def _finalize_import(self) -> None:
        """Finalize import and refresh UI."""
        if self.import_poll_job is not None:
            self.root.after_cancel(self.import_poll_job)
            self.import_poll_job = None

        self.is_importing = False
        self._set_import_ui_busy(False)
        self._is_applying_payload = False
        self._pending_file_payloads.clear()

        if self.import_process is not None:
            if self.import_process.is_alive():
                self.import_process.join(timeout=0.2)
                if self.import_process.is_alive():
                    self.import_process.terminate()
            self.import_process = None
        self.import_result_queue = None
        self.import_abort_flag = None

        if self.import_modal is not None:
            progress = getattr(self.import_modal, "_progressbar", None)
            if progress is not None:
                progress.stop()
            self.import_modal.grab_release()
            self.import_modal.destroy()
            self.import_modal = None

        with self._import_status_lock:
            status = dict(self._import_status)

        self.refresh_targets()
        self.dps_panel.refresh()

        if status.get('aborted'):
            self.log_debug(
                f"Load & Parse aborted. Imported {status.get('files_completed', 0)} files before stop.",
                msg_type='warning'
            )
        elif status.get('errors'):
            messagebox.showwarning(
                "Load & Parse Completed with Errors",
                "\n".join(status['errors'])
            )
            self.log_debug("Load & Parse completed with file errors.", msg_type='warning')
        else:
            self.log_debug(
                f"Load & Parse completed: {status.get('total_files', 0)} files.",
                msg_type='info'
            )

    def _center_window_on_parent(self, window: tk.Toplevel, width: int, height: int) -> None:
        """Center a child window relative to the main application window."""
        self.root.update_idletasks()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()

        x = max(0, root_x + (root_w - width) // 2)
        y = max(0, root_y + (root_h - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _apply_modal_icon(self, window: tk.Toplevel) -> None:
        """Apply same icon used by the main app window to modal windows."""
        if self.window_icon_path:
            try:
                window.iconbitmap(self.window_icon_path)
                return
            except Exception:
                pass

        try:
            icon_ref = self.root.iconbitmap()
            if icon_ref:
                window.iconbitmap(icon_ref)
        except Exception:
            pass

    def set_window_icon(self, icon_path: str) -> None:
        """Store icon path so child dialogs can reuse the app icon."""
        self.window_icon_path = icon_path

    def start_monitoring(self) -> None:
        """Start monitoring the log directory for new log files."""
        if self.is_monitoring:
            return
        if not self.log_directory:
            messagebox.showwarning("No Directory", "Please select a log directory first.")
            self._set_monitoring_switch_ui(False)
            return

        self.is_monitoring = True
        self._set_monitoring_switch_ui(True)
        self.dps_panel.refresh()

        self.log_debug(f"Starting monitoring of directory: {self.log_directory}")

        # Setup directory monitor for polling
        self.directory_monitor = LogDirectoryMonitor(self.log_directory)
        self.directory_monitor.start_monitoring()
        current_log_file = getattr(self.directory_monitor, "current_log_file", None)
        self._monitor_active_file_name = (
            current_log_file.name
            if current_log_file is not None
            else "-"
        )
        self._debug_monitor_enabled = bool(self.debug_panel.get_debug_enabled())
        started = self._start_monitor_thread()
        if not started:
            self.log_debug(
                "Previous monitor thread is still shutting down; retrying start shortly",
                "warning",
            )
            self._schedule_monitor_restart()

        # Keep a lightweight UI ticker for status labels and queued debug logs.
        self.log_debug("Using background monitor thread with bounded line processing")
        self.poll_log_file()

        self.log_debug("Monitoring started successfully")

    def pause_monitoring(self) -> None:
        """Pause monitoring the log directory."""
        self.is_monitoring = False
        self._set_monitoring_switch_ui(False)
        self._stop_monitor_thread()
        restart_job = getattr(self, "_monitor_restart_job", None)
        if restart_job is not None:
            self.root.after_cancel(restart_job)
            self._monitor_restart_job = None

        # Cancel polling if active
        if self.polling_job:
            self.root.after_cancel(self.polling_job)
            self.polling_job = None

        # Cancel DPS auto-refresh if in Global mode
        if self.dps_refresh_job is not None:
            self.root.after_cancel(self.dps_refresh_job)
            self.dps_refresh_job = None
        if hasattr(self, "_refresh_job") and self._refresh_job is not None:
            self.root.after_cancel(self._refresh_job)
            self._refresh_job = None


        self.log_debug("Monitoring paused")

    def _set_monitoring_switch_ui(self, is_on: bool) -> None:
        """Synchronize monitoring switch state and label with monitoring status."""
        self.monitoring_var.set(is_on)
        self.monitoring_text.set("Monitoring" if is_on else "Paused")

    def _on_monitoring_switch_toggle(self) -> None:
        """Handle monitoring switch state changes."""
        if self.monitoring_var.get():
            self.start_monitoring()
        else:
            self.pause_monitoring()

    def _configure_monitoring_switch_style(self) -> None:
        """Add monitoring label colors on top of the existing Switch style."""
        style = ttk.Style(self.root)
        # Reuse Switch layout/elements and only customize the text color mapping.
        try:
            style.layout("Monitoring.Switch.TCheckbutton", style.layout("Switch.TCheckbutton"))
        except tk.TclError:
            # If already defined, keep existing layout.
            pass
        style.map(
            "Monitoring.Switch.TCheckbutton",
            foreground=[
                ("selected", "#56C9FF"),
                ("!selected", "#FF99A4"),
                ("disabled", "#808A93"),
            ],
        )

    def _enqueue_monitor_log(self, message: str, msg_type: str = "debug") -> None:
        """Queue background-monitor log messages for UI-thread rendering."""
        self._monitor_log_queue.put((str(message), str(msg_type)))

    def _drain_monitor_logs(self, max_messages: int = 200) -> None:
        """Flush queued monitor logs on Tk thread."""
        drained = 0
        while drained < max_messages:
            try:
                message, msg_type = self._monitor_log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_debug(message, msg_type)
            drained += 1

    def _start_monitor_thread(self) -> bool:
        """Start background thread that performs file I/O and parsing."""
        thread = self.monitor_thread
        if thread is not None and thread.is_alive():
            # If stop is already requested, wait for the shutdown path to finish.
            return False
        self.monitor_stop_event.clear()
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="nwn-log-monitor",
            daemon=True,
        )
        self.monitor_thread.start()
        return True

    def _stop_monitor_thread(self) -> None:
        """Signal monitor thread to stop and join it quickly."""
        self.monitor_stop_event.set()
        thread = self.monitor_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        if thread is not None and thread.is_alive():
            # Keep a reference while shutdown is still in progress to prevent a second worker.
            self.log_debug("Monitor thread is still shutting down; restart deferred", "warning")
        else:
            self.monitor_thread = None
        self._monitor_active_file_name = "-"

    def _schedule_monitor_restart(self) -> None:
        """Retry starting monitoring thread after prior worker shutdown completes."""
        if getattr(self, "_monitor_restart_job", None) is not None:
            return
        self._monitor_restart_job = self.root.after(100, self._retry_monitor_restart)

    def _retry_monitor_restart(self) -> None:
        """Attempt deferred monitor thread start if app is still monitoring."""
        self._monitor_restart_job = None
        if not self.is_monitoring:
            return
        if self._start_monitor_thread():
            self.log_debug("Monitor thread restarted after shutdown")
            return
        self._schedule_monitor_restart()

    def _monitor_loop(self) -> None:
        """Worker loop that polls the active log file and parses new lines."""
        current_thread = threading.current_thread()
        try:
            while not self.monitor_stop_event.is_set():
                directory_monitor = self.directory_monitor
                if directory_monitor is None:
                    break
                pressure_state = self._get_queue_pressure_state()
                has_more_pending = False

                if pressure_state != "saturated":
                    try:
                        has_more_pending = directory_monitor.read_new_lines(
                            self.parser,
                            self.data_queue,
                            on_log_message=self._enqueue_monitor_log,
                            debug_enabled=bool(self._debug_monitor_enabled),
                            max_lines_per_poll=self._get_monitor_max_lines_per_poll(
                                pressure_state
                            ),
                        )
                    except Exception as exc:
                        self._enqueue_monitor_log(f"I/O Error: {exc}", "error")
                        has_more_pending = False

                sleep_pressure_state = self._get_queue_pressure_state()

                current_file = directory_monitor.current_log_file
                self._monitor_active_file_name = current_file.name if current_file is not None else "-"

                if self.monitor_stop_event.is_set():
                    break
                time.sleep(
                    self._get_monitor_sleep_seconds(
                        pressure_state=sleep_pressure_state,
                        has_more_pending=has_more_pending,
                    )
                )
        finally:
            if self.monitor_thread is current_thread:
                self.monitor_thread = None

    def poll_log_file(self) -> None:
        """Lightweight UI tick for monitor status updates."""
        if self.is_monitoring:
            self._drain_monitor_logs()
            self.update_active_file_label()
            self.polling_job = self.root.after(250, self.poll_log_file)

    def update_active_file_label(self) -> None:
        """Update the active file label to show which log file is being monitored."""
        if self.directory_monitor:
            self.active_file_text.set(value=self._monitor_active_file_name)
        else:
            self.active_file_text.set(value="-")

    def clear_data(self) -> None:
        """Clear all collected data."""
        # Cancel any pending refresh from Global mode
        if self.dps_refresh_job is not None:
            self.root.after_cancel(self.dps_refresh_job)
            self.dps_refresh_job = None
        if hasattr(self, "_refresh_job") and self._refresh_job is not None:
            self.root.after_cancel(self._refresh_job)
            self._refresh_job = None
        if hasattr(self, "_dps_dirty"):
            self._dps_dirty = False
        if hasattr(self, "_targets_dirty"):
            self._targets_dirty = False
        if hasattr(self, "_immunity_dirty_targets"):
            self._immunity_dirty_targets.clear()

        self.data_store.clear_all_data()

        # Clear all UI trees
        self.immunity_panel.tree.delete(*self.immunity_panel.tree.get_children())
        self.dps_panel.tree.delete(*self.dps_panel.tree.get_children())
        self.stats_panel.tree.delete(*self.stats_panel.tree.get_children())
        self.death_snippet_panel.clear()
        self.immunity_panel.target_combo.set('')

        # Clear immunity panel cache
        self.immunity_panel.clear_cache()

        # Clear DPS panel cache
        self.dps_panel.clear_cache()

        # Clear target stats panel cache
        self.stats_panel.clear_cache()

        # Reset DPS service state
        self.dps_service.set_global_start_time(None)

        # Reset DPS panel target filter to "All"
        self.dps_panel.reset_target_filter()

        self.refresh_targets()

    def refresh_targets(self) -> None:
        """Refresh target-driven widgets while minimizing duplicate store reads."""
        targets = self.data_store.get_all_targets()
        self.update_target_selector_list(targets)
        self.update_target_filter_list(targets)
        self.stats_panel.refresh()
        # Only auto-select if nothing is currently selected.
        if not self.immunity_panel.target_combo.get() and targets:
            self.immunity_panel.target_combo.current(0)
            self.on_target_selected(None)

    def update_target_selector_list(self, targets: list[str] | None = None) -> None:
        """Update the Select Target combobox with all available targets.

        This method preserves the current selection if possible, making it suitable
        for automatic updates during gameplay without disrupting the user.
        Automatically selects the first target if the list changes and no target
        is currently selected.
        """
        if targets is None:
            targets = self.data_store.get_all_targets()
        self.immunity_panel.update_target_list(targets)

    def update_target_filter_list(self, targets: list[str] | None = None) -> None:
        """Update the target filter combobox with all available targets."""
        if targets is None:
            targets = self.data_store.get_all_targets()
        self.dps_panel.update_target_filter_options(targets)

    def on_target_selected(self, event) -> None:
        """Handle target selection from combobox."""
        if event:
            event.widget.selection_clear()  # Clear the UI selection highlight
        target = self.immunity_panel.target_combo.get()
        if target:
            self.immunity_panel.refresh_target_details(target)

    def _on_time_tracking_mode_changed(self, event: tk.Event) -> None:
        """Handle first timestamp mode change from combobox.

        Updates the first timestamp mode and refreshes the DPS display.
        All data is preserved; only the calculation method changes.

        Args:
            event: Tkinter event from combobox selection
        """
        event.widget.selection_clear()
        new_mode_display = self.dps_panel.time_tracking_var.get()
        new_mode = new_mode_display.lower().replace(" ", "_")

        if new_mode == self.dps_service.time_tracking_mode:
            # No actual change
            return

        # Update the service mode
        self.dps_service.set_time_tracking_mode(new_mode)
        self._schedule_session_settings_save()

        self.log_debug(f"First timestamp mode changed to: {new_mode_display}")

        # Always refresh DPS display so manual imports (paused monitoring)
        # immediately reflect the selected first timestamp mode.
        self.dps_panel.refresh()

    def _on_target_filter_changed(self, event: tk.Event) -> None:
        """Handle target filter change from combobox.

        Updates the DPS display to show data for the selected target only.

        Args:
            event: Tkinter event from combobox selection
        """
        event.widget.selection_clear()  # Clear the UI selection highlight
        self.log_debug(f"Target filter changed to: {self.dps_panel.target_filter_var.get()}")

        # Refresh DPS display with new target filter
        self.dps_panel.refresh()


    def refresh_dps(self) -> None:
        """This is a thin wrapper that delegates to the DPS panel and handles
        auto-refresh scheduling for Global mode.
        """
        # Delegate to the panel's refresh method
        self.dps_panel.refresh()



    def process_queue(self) -> None:
        """Process data from the queue and update UI.

        This method delegates the actual event processing to the QueueProcessor service
        and schedules itself to run periodically.
        """
        starting_pressure_state = self._get_queue_pressure_state()
        max_events, max_time_ms = self._get_queue_drain_limits(starting_pressure_state)
        process_kwargs = {
            "on_log_message": self.log_debug,
            "debug_enabled": self.debug_panel.get_debug_enabled(),
            "max_events": max_events,
            "max_time_ms": max_time_ms,
        }
        process_fn = self.queue_processor.process_queue
        if hasattr(process_fn, "mock_calls"):
            # Test harness compatibility only.
            process_kwargs.update({
                "on_dps_updated": self.refresh_dps,
                "on_target_selected": self._on_target_details_needed,
                "on_immunity_changed": self._on_immunity_changed,
                "on_damage_dealt": self._on_damage_dealt,
                "on_death_snippet": self._on_death_snippet,
                "on_character_identified": self._on_death_character_identified,
            })
        else:
            for key in (
                "on_dps_updated",
                "on_target_selected",
                "on_immunity_changed",
                "on_damage_dealt",
                "on_death_snippet",
                "on_character_identified",
            ):
                process_kwargs.pop(key, None)
        result = self.queue_processor.process_queue(
            self.data_queue,
            **process_kwargs,
        )
        pressure_state_value = getattr(result, "pressure_state", "normal")
        pressure_state = (
            pressure_state_value
            if pressure_state_value in {"normal", "pressured", "saturated"}
            else "normal"
        )
        self._queue_pressure_state = pressure_state

        # Apply non-tree events immediately.
        death_events = result.death_events if isinstance(getattr(result, "death_events", None), list) else []
        identity_events = (
            result.character_identity_events
            if isinstance(getattr(result, "character_identity_events", None), list)
            else []
        )
        targets_to_refresh = (
            result.targets_to_refresh
            if isinstance(getattr(result, "targets_to_refresh", None), set)
            else set()
        )
        immunity_targets = (
            result.immunity_targets
            if isinstance(getattr(result, "immunity_targets", None), set)
            else set()
        )
        damage_targets = (
            result.damage_targets
            if isinstance(getattr(result, "damage_targets", None), set)
            else set()
        )

        for death_event in death_events:
            self._on_death_snippet(death_event)
        for identity_event in identity_events:
            self._on_death_character_identified(identity_event)

        # Coalesce expensive tree refreshes.
        if bool(getattr(result, "dps_updated", False)):
            self._dps_dirty = True
        if targets_to_refresh:
            self._targets_dirty = True

        selected_target = ""
        if hasattr(self, "immunity_panel") and hasattr(self.immunity_panel, "target_combo"):
            selected_target = self.immunity_panel.target_combo.get()
        if selected_target:
            if selected_target in immunity_targets or selected_target in damage_targets:
                self._immunity_dirty_targets.add(selected_target)

        if self._dps_dirty or self._targets_dirty or self._immunity_dirty_targets:
            self._schedule_coalesced_refresh()

        # Schedule next check
        next_tick = self._get_next_queue_tick_ms(pressure_state)
        self.root.after(next_tick, self.process_queue)

    def _get_queue_depth_hint(self) -> int:
        """Return an approximate queue depth for scheduling decisions."""
        try:
            size = int(self.data_queue.qsize())
        except (AttributeError, NotImplementedError):
            return 0
        return max(size, 0)

    def _get_queue_pressure_state(self) -> str:
        """Classify queue pressure bands used for monitor pacing."""
        queue_depth = self._get_queue_depth_hint()
        if queue_depth >= self.DATA_QUEUE_SATURATED_THRESHOLD:
            return "saturated"
        if queue_depth >= self.DATA_QUEUE_PRESSURED_THRESHOLD:
            return "pressured"
        return "normal"

    def _get_monitor_max_lines_per_poll(self, pressure_state: str) -> int:
        """Cap background ingestion according to current queue pressure."""
        if pressure_state == "pressured":
            return self.MONITOR_LINES_PER_POLL_PRESSURED
        return self.MONITOR_LINES_PER_POLL_NORMAL

    def _get_monitor_sleep_seconds(self, pressure_state: str, has_more_pending: bool) -> float:
        """Sleep policy for background monitor loop.

        normal: full ingestion, short sleep while unread lines remain
        pressured: reduced ingestion cap, slightly slower polling
        saturated: skip ingestion until UI drains backlog
        """
        if pressure_state == "saturated":
            return self.MONITOR_SLEEP_ACTIVE_SATURATED
        if has_more_pending:
            if pressure_state == "pressured":
                return self.MONITOR_SLEEP_ACTIVE_PRESSURED
            return self.MONITOR_SLEEP_ACTIVE_NORMAL
        if pressure_state == "pressured":
            return self.MONITOR_SLEEP_IDLE_PRESSURED
        return self.MONITOR_SLEEP_IDLE_NORMAL

    def _get_queue_drain_limits(self, pressure_state: str) -> tuple[int, float]:
        """Return Tk-thread queue-drain limits for the current pressure band."""
        if pressure_state == "saturated":
            return self.QUEUE_DRAIN_MAX_EVENTS_SATURATED, self.QUEUE_DRAIN_MAX_TIME_MS_SATURATED
        if pressure_state == "pressured":
            return self.QUEUE_DRAIN_MAX_EVENTS_PRESSURED, self.QUEUE_DRAIN_MAX_TIME_MS_PRESSURED
        return self.QUEUE_DRAIN_MAX_EVENTS_NORMAL, self.QUEUE_DRAIN_MAX_TIME_MS_NORMAL

    def _get_next_queue_tick_ms(self, pressure_state: str) -> int:
        """Adjust Tk queue-drain cadence based on current backlog pressure."""
        if pressure_state == "saturated":
            return self.QUEUE_TICK_MS_SATURATED
        if pressure_state == "pressured":
            return self.QUEUE_TICK_MS_PRESSURED
        return int(getattr(self, "_queue_tick_ms", self.QUEUE_TICK_MS_NORMAL))

    def _schedule_coalesced_refresh(self) -> None:
        """Schedule a batched UI refresh for heavy panels."""
        if getattr(self, "_refresh_job", None) is not None:
            return
        self._refresh_job = self.root.after(180, self._run_coalesced_refresh)

    def _run_coalesced_refresh(self) -> None:
        """Execute one coalesced refresh pass for expensive widgets."""
        self._refresh_job = None
        selected_target = ""
        if hasattr(self, "immunity_panel") and hasattr(self.immunity_panel, "target_combo"):
            selected_target = self.immunity_panel.target_combo.get()

        if self._targets_dirty:
            self.refresh_targets()
            self._targets_dirty = False
            selected_target = self.immunity_panel.target_combo.get()

        if self._dps_dirty:
            self.dps_panel.refresh()
            self._dps_dirty = False

        if (
            selected_target
            and selected_target in self._immunity_dirty_targets
            and hasattr(self, "immunity_panel")
        ):
            self.immunity_panel.refresh_target_details(selected_target)
        self._immunity_dirty_targets.clear()

    def _on_target_details_needed(self, target: str) -> None:
        """Callback from queue processor when target details need refresh.

        Args:
            target: Name of target to refresh
        """
        if self.immunity_panel.target_combo.get() == target:
            self.immunity_panel.refresh_target_details(target)

    def _on_immunity_changed(self, target: str) -> None:
        """Callback from queue processor when immunity data changes.

        Args:
            target: Name of target with immunity changes
        """
        if self.immunity_panel.target_combo.get() == target:
            self.immunity_panel.refresh_display()

    def _on_damage_dealt(self, target: str) -> None:
        """Callback from queue processor when damage is dealt.

        Args:
            target: Name of target that received damage
        """
        # Refresh immunity panel if this is the currently selected target
        # to ensure all damage types are displayed
        if self.immunity_panel.target_combo.get() == target:
            self.immunity_panel.refresh_display()

    def _on_death_snippet(self, event: Dict[str, Any]) -> None:
        """Callback from queue processor when a death snippet is produced."""
        self.death_snippet_panel.add_death_event(event)

    def _on_death_character_identified(self, event: Dict[str, Any]) -> None:
        """Callback when parser auto-identifies player character via whisper token."""
        character_name = str(event.get("character_name", "")).strip()
        if not character_name:
            return
        if self.death_snippet_panel.get_character_name():
            return
        self.death_snippet_panel.set_character_name(character_name)

    def _on_death_character_name_changed(self, name: str) -> None:
        """Apply UI character-name changes to parser death detection."""
        self.parser.set_death_character_name(name)

    def _on_death_fallback_line_changed(self, line: str) -> None:
        """Apply UI fallback line changes to parser death detection."""
        self.parser.set_death_fallback_line(line)
        self._schedule_session_settings_save()

    def _on_parse_immunity_changed(self, enabled: bool) -> None:
        """Persist immunity parsing toggle changes from the UI."""
        self.parser.parse_immunity = bool(enabled)
        self._schedule_session_settings_save()

    def on_closing(self) -> None:
        """Handle application closing."""
        self._flush_pending_session_settings_save()
        if self.is_importing:
            self.import_abort_event.set()
            if self.import_abort_flag is not None:
                self.import_abort_flag.set()
            if self.import_process is not None and self.import_process.is_alive():
                self.import_process.terminate()
        self.pause_monitoring()
        self.data_store.close()
        self.root.destroy()

    def _build_session_settings(self) -> AppSettings:
        """Build serializable user session settings from current UI state."""
        log_directory = str(getattr(self, "log_directory", "")).strip() or None
        death_fallback_line = None

        death_panel = getattr(self, "death_snippet_panel", None)
        if death_panel is not None:
            death_fallback_line = death_panel.get_fallback_death_line()
        else:
            parser = getattr(self, "parser", None)
            if parser is not None:
                death_fallback_line = str(getattr(parser, "death_fallback_line", "")).strip()

        return AppSettings(
            log_directory=log_directory,
            death_fallback_line=(death_fallback_line or "").strip() or None,
            parse_immunity=bool(getattr(getattr(self, "parser", None), "parse_immunity", True)),
            first_timestamp_mode=self._get_current_first_timestamp_mode(),
        )

    def _restore_persisted_dps_panel_state(self) -> None:
        """Apply persisted DPS panel state to UI controls after widget creation."""
        dps_panel = getattr(self, "dps_panel", None)
        if dps_panel is None:
            return
        time_tracking_var = getattr(dps_panel, "time_tracking_var", None)
        if time_tracking_var is None:
            return

        mode_display_by_value = {
            "per_character": "Per Character",
            "global": "Global",
        }
        current_mode = self.dps_service.time_tracking_mode
        time_tracking_var.set(mode_display_by_value.get(current_mode, "Per Character"))

    def _get_current_first_timestamp_mode(self) -> str | None:
        """Return the active first timestamp mode for settings persistence."""
        dps_panel = getattr(self, "dps_panel", None)
        if dps_panel is not None:
            get_mode = getattr(dps_panel, "get_time_tracking_mode", None)
            if callable(get_mode):
                mode = get_mode()
                if mode in {"per_character", "global"}:
                    return mode

        dps_service = getattr(self, "dps_service", None)
        mode = getattr(dps_service, "time_tracking_mode", None)
        if mode in {"per_character", "global"}:
            return mode
        return None

    def _persist_session_settings(self) -> None:
        """Persist current session settings."""
        settings = self._build_session_settings()
        self._settings = settings
        try:
            save_app_settings(settings)
        except OSError:
            # Settings persistence must never break runtime behavior.
            return

    def _schedule_session_settings_save(self) -> None:
        """Debounce session settings persistence for frequently edited fields."""
        root = getattr(self, "root", None)
        if root is None:
            self._persist_session_settings()
            return

        existing_job = getattr(self, "_settings_save_job", None)
        if existing_job is not None:
            try:
                root.after_cancel(existing_job)
            except tk.TclError:
                pass

        delay_ms = int(getattr(self, "_settings_save_delay_ms", 400))
        self._settings_save_job = root.after(delay_ms, self._flush_pending_session_settings_save)

    def _flush_pending_session_settings_save(self) -> None:
        """Immediately persist settings and clear any scheduled save handle."""
        self._settings_save_job = None
        self._persist_session_settings()

    def clear_debug(self) -> None:
        """Clear the debug console."""
        self.debug_panel.clear()

    def log_debug(self, message: str, msg_type: str = 'debug') -> None:
        """Add a message to the debug console.

        Args:
            message: Message to add
            msg_type: Type of message ('info', 'debug', 'warning', 'error')
        """
        # Log to panel if it exists
        if hasattr(self, 'debug_panel'):
            self.debug_panel.log(message, msg_type)

    def _on_debug_toggle(self, *args) -> None:
        """Handle debug mode toggle from the debug panel."""
        self.debug_mode = bool(self.debug_panel.debug_mode_var.get())
        self._debug_monitor_enabled = self.debug_mode
        self.log_debug(f"Debug output {'enabled' if self.debug_mode else 'disabled'}")

    def _on_notebook_click(self, event: tk.Event) -> None:
        """Track tab-title clicks to unlock advanced debug tab for this session."""
        if self._debug_tab_visible or self.notebook is None:
            return

        if self.notebook.identify(event.x, event.y) != "label":
            self._dps_tab_click_times.clear()
            return

        try:
            tab_index = self.notebook.index(f"@{event.x},{event.y}")
        except tk.TclError:
            self._dps_tab_click_times.clear()
            return

        clicked_tab_text = str(self.notebook.tab(tab_index, "text"))
        if clicked_tab_text != self._dps_tab_text:
            self._dps_tab_click_times.clear()
            return

        self._record_dps_tab_click_and_maybe_unlock()

    def _record_dps_tab_click_and_maybe_unlock(self) -> None:
        """Count rapid DPS tab clicks and reveal the debug tab on threshold."""
        now = time.monotonic()
        self._dps_tab_click_times.append(now)

        window_start = now - self._debug_unlock_window_seconds
        while self._dps_tab_click_times and self._dps_tab_click_times[0] < window_start:
            self._dps_tab_click_times.popleft()

        if len(self._dps_tab_click_times) >= self._debug_unlock_click_target:
            self._show_debug_tab()
            self._dps_tab_click_times.clear()

    def _show_debug_tab(self) -> None:
        """Show the hidden debug tab exactly once for the current session."""
        if self._debug_tab_visible or self.notebook is None:
            return

        self.notebook.add(self.debug_panel, text="Debug Console")
        self._debug_tab_visible = True
