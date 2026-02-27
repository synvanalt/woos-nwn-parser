"""Main application window for Woo's NWN Parser.

This module contains the WoosNwnParserApp class which manages the main
application window, UI components, and event processing.
"""

import queue
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font

from ..parser import LogParser
from ..storage import DataStore
from ..monitor import LogDirectoryMonitor
from ..utils import parse_and_import_file
from ..services import QueueProcessor, DPSCalculationService
from .formatters import get_default_log_directory
from .widgets import DPSPanel, TargetStatsPanel, ImmunityPanel, DebugConsolePanel


class WoosNwnParserApp:
    """Main application window."""

    def __init__(self, root: tk.Tk) -> None:
        """Initialize the application.

        Args:
            root: The root Tkinter window
        """
        self.root = root
        self.root.title("Woo's NWN Parser")
        self.root.geometry("730x550")

        # Core services
        # By default, we do not parse immunity values (lightweight mode)
        self.parser = LogParser(parse_immunity=False)
        self.data_store = DataStore()
        self.queue_processor = QueueProcessor(self.data_store, self.parser)
        self.dps_service = DPSCalculationService(self.data_store)

        # Queue and monitoring
        self.data_queue = queue.Queue()
        self.directory_monitor: Optional[LogDirectoryMonitor] = None
        self.is_monitoring = False
        self.log_directory = get_default_log_directory()

        # Polling and refresh jobs
        self.polling_job = None
        self.dps_refresh_job = None

        # Version tracking for dirty checking (avoids redundant refreshes)
        self._last_refresh_version: int = 0

        # Debug mode
        self.debug_mode = False
        self.is_importing = False
        self.import_abort_event = threading.Event()
        self.import_thread: Optional[threading.Thread] = None
        self.import_poll_job = None
        self.import_modal: Optional[tk.Toplevel] = None
        self.import_status_text: Optional[tk.StringVar] = None
        self.import_progress_text: Optional[tk.StringVar] = None
        self.import_abort_button: Optional[ttk.Button] = None
        self.monitoring_was_active_before_import = False
        self._import_status_lock = threading.Lock()
        self._import_status: Dict[str, Any] = {}

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

        self.load_parse_button = ttk.Button(buttons_frame, text="Load & Parse", command=self.load_and_parse_selected_files)
        self.load_parse_button.pack(side="left", padx=5)
        self.reset_button = ttk.Button(buttons_frame, text="Reset Data", command=self.reset_data)
        self.reset_button.pack(side="left", padx=5)


        # Initialize directory label with default if available
        if self.log_directory:
            dir_display = self.log_directory.replace("/", "\\")
            self.dir_text.set(value=dir_display)

        # Main content area with notebook for multiple targets
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        # Tab 1: DPS Panel (using DPSPanel widget)
        self.dps_panel = DPSPanel(notebook, self.data_store, self.dps_service)
        notebook.add(self.dps_panel, text="Damage Per Second")
        self.dps_panel.time_tracking_combo.bind("<<ComboboxSelected>>", self._on_time_tracking_mode_changed)
        self.dps_panel.target_filter_combo.bind("<<ComboboxSelected>>", self._on_target_filter_changed)

        # Tab 2: Target Stats Panel (using TargetStatsPanel widget)
        self.stats_panel = TargetStatsPanel(notebook, self.data_store, self.parser)
        notebook.add(self.stats_panel, text="Target Stats")

        # Tab 3: Immunity Panel (using ImmunityPanel widget)
        self.immunity_panel = ImmunityPanel(notebook, self.data_store, self.parser)
        notebook.add(self.immunity_panel, text="Target Immunities")
        self.immunity_panel.target_combo.bind("<<ComboboxSelected>>", self.on_target_selected)

        # Tab 4: Debug Console Panel (using DebugConsolePanel widget)
        self.debug_panel = DebugConsolePanel(notebook)
        notebook.add(self.debug_panel, text="Debug Console")
        self.debug_panel.debug_mode_var.trace("w", self._on_debug_toggle)

        # Store references for backward compatibility
        self.dps_tree = self.dps_panel.tree
        self.target_summary_tree = self.stats_panel.tree
        self.resist_tree = self.immunity_panel.tree
        self.target_combo = self.immunity_panel.target_combo
        self.parse_immunity_var = self.immunity_panel.parse_immunity_var
        self.debug_mode_var = self.debug_panel.debug_mode_var
        self.debug_text = self.debug_panel.text
        self.time_tracking_var = self.dps_panel.time_tracking_var
        self.target_filter_var = self.dps_panel.target_filter_var

    # ...existing code...
    def browse_directory(self) -> None:
        """Open directory dialog to select log directory."""
        directory = filedialog.askdirectory(
            title="Select Log Directory (contains nwclientLog*.txt files)"
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

    def load_and_parse_selected_files(self) -> None:
        """Open file picker and parse selected .txt logs in a background worker."""
        if self.is_importing:
            return

        selected_paths = filedialog.askopenfilenames(
            title="Select one or more NWN log files",
            filetypes=[("Text Files", "*.txt")],
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
            'lines_processed': 0,
            'file_lines_processed': 0,
            'errors': [],
            'aborted': False,
            'success': False,
        }

        self._set_import_ui_busy(True)
        self._show_import_modal()
        self._start_import_worker(selected_files)
        self._poll_import_progress()

    def load_and_parse_directory(self) -> None:
        """Backwards-compatible wrapper for selected-file import."""
        self.load_and_parse_selected_files()

    def _set_import_ui_busy(self, is_busy: bool) -> None:
        """Disable/enable controls while import is running."""
        state = tk.DISABLED if is_busy else tk.NORMAL
        self.monitoring_switch.config(state=state)
        self.browse_button.config(state=state)
        self.load_parse_button.config(state=state)
        self.reset_button.config(state=state)

    def _show_import_modal(self) -> None:
        """Show a modal with import progress and abort button."""
        self.import_modal = tk.Toplevel(self.root)
        self.import_modal.title("Loading Logs")
        self.import_modal.geometry("480x180")
        self.import_modal.resizable(False, False)
        self.import_modal.transient(self.root)
        self.import_modal.grab_set()
        self.import_modal.protocol("WM_DELETE_WINDOW", self.abort_load_parse)

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
        self.import_abort_button.pack(anchor="e", pady=(14, 0))

    def _start_import_worker(self, selected_files: List[Path]) -> None:
        """Start worker thread for import operation."""
        self.import_thread = threading.Thread(
            target=self._run_import_worker,
            args=(selected_files,),
            daemon=True,
        )
        self.import_thread.start()

    def _run_import_worker(self, selected_files: List[Path]) -> None:
        """Parse selected files and update shared status."""
        total_lines = 0
        file_errors: List[str] = []

        for index, log_file in enumerate(selected_files, start=1):
            if self.import_abort_event.is_set():
                with self._import_status_lock:
                    self._import_status['aborted'] = True
                    self._import_status['files_completed'] = index - 1
                return

            with self._import_status_lock:
                self._import_status['current_file'] = log_file.name
                self._import_status['files_completed'] = index - 1
                self._import_status['file_lines_processed'] = 0

            def _on_file_progress(lines_processed: int) -> None:
                with self._import_status_lock:
                    self._import_status['file_lines_processed'] = lines_processed

            result = parse_and_import_file(
                str(log_file),
                self.parser,
                self.data_store,
                should_abort=self.import_abort_event.is_set,
                progress_callback=_on_file_progress,
            )

            if result.get('aborted'):
                with self._import_status_lock:
                    self._import_status['aborted'] = True
                    self._import_status['files_completed'] = index - 1
                return

            if result['success']:
                lines = result['lines_processed']
                total_lines += lines
                with self._import_status_lock:
                    self._import_status['lines_processed'] = total_lines
                    self._import_status['files_completed'] = index
            else:
                error_message = f"{log_file.name}: {result['error']}"
                file_errors.append(error_message)
                with self._import_status_lock:
                    self._import_status['errors'] = list(file_errors)
                    self._import_status['files_completed'] = index

        with self._import_status_lock:
            self._import_status['success'] = True
            self._import_status['lines_processed'] = total_lines
            self._import_status['errors'] = list(file_errors)

    def _poll_import_progress(self) -> None:
        """Update modal with latest import status."""
        if not self.is_importing:
            return

        with self._import_status_lock:
            status = dict(self._import_status)

        if self.import_status_text is not None:
            current_file = status.get('current_file') or "Preparing selected files..."
            file_lines = status.get('file_lines_processed', 0)
            self.import_status_text.set(
                f"Parsing {current_file} ({file_lines} lines processed in current file)"
            )
        if self.import_progress_text is not None:
            self.import_progress_text.set(
                f"{status.get('files_completed', 0)}/{status.get('total_files', 0)} files completed "
                f"({status.get('lines_processed', 0)} total lines)"
            )

        if self.import_thread and self.import_thread.is_alive():
            self.import_poll_job = self.root.after(100, self._poll_import_progress)
            return

        self._finalize_import()

    def abort_load_parse(self) -> None:
        """Request abort for ongoing import."""
        if not self.is_importing:
            return
        self.import_abort_event.set()
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
                f"Load & Parse aborted. Imported {status.get('files_completed', 0)} files and "
                f"{status.get('lines_processed', 0)} lines before stop.",
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
                f"Load & Parse completed: {status.get('total_files', 0)} files, "
                f"{status.get('lines_processed', 0)} total lines.",
                msg_type='info'
            )

    def start_monitoring(self) -> None:
        """Start monitoring the log directory for new log files."""
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

        # Use manual polling (checking every 500ms)
        self.log_debug("Using polling mode (checking every 500ms)")
        self.poll_log_file()

        self.log_debug("Monitoring started successfully")

    def pause_monitoring(self) -> None:
        """Pause monitoring the log directory."""
        self.is_monitoring = False
        self._set_monitoring_switch_ui(False)

        # Cancel polling if active
        if self.polling_job:
            self.root.after_cancel(self.polling_job)
            self.polling_job = None

        # Cancel DPS auto-refresh if in Global mode
        if self.dps_refresh_job is not None:
            self.root.after_cancel(self.dps_refresh_job)
            self.dps_refresh_job = None


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

    def poll_log_file(self) -> None:
        """Manually poll the log directory for changes."""
        if self.is_monitoring and self.directory_monitor:
            self.directory_monitor.read_new_lines(
                self.parser,
                self.data_queue,
                on_log_message=self.log_debug,
                debug_enabled=self.debug_panel.get_debug_enabled()
            )
            # Update the active file label
            self.update_active_file_label()
            # Only refresh targets if data has changed (dirty checking)
            current_version = self.data_store.version
            if current_version != self._last_refresh_version:
                self.refresh_targets()
                self._last_refresh_version = current_version
            # Schedule next poll in 500ms
            self.polling_job = self.root.after(500, self.poll_log_file)

    def update_active_file_label(self) -> None:
        """Update the active file label to show which log file is being monitored."""
        if self.directory_monitor:
            active_file = self.directory_monitor.get_active_log_file()
            if active_file:
                self.active_file_text.set(value=active_file.name)
            else:
                self.active_file_text.set(value="-")

    def reset_data(self) -> None:
        """Clear all collected data."""
        # Cancel any pending refresh from Global mode
        if self.dps_refresh_job is not None:
            self.root.after_cancel(self.dps_refresh_job)
            self.dps_refresh_job = None

        self.data_store.clear_all_data()
        self.parser.target_ac.clear()
        self.parser.target_saves.clear()
        self.parser.target_attack_bonus.clear()

        # Clear all UI trees
        self.resist_tree.delete(*self.resist_tree.get_children())
        self.dps_tree.delete(*self.dps_tree.get_children())
        self.target_summary_tree.delete(*self.target_summary_tree.get_children())
        self.target_combo.set('')

        # Clear immunity panel cache
        self.immunity_panel.clear_cache()

        # Clear DPS panel cache
        self.dps_panel.clear_cache()

        # Reset DPS service state
        self.dps_service.set_global_start_time(None)

        # Reset DPS panel target filter to "All"
        self.dps_panel.reset_target_filter()

        self.refresh_targets()

    def refresh_targets(self) -> None:
        """Refresh the list of targets in the combobox and select first if none selected."""
        self.update_target_selector_list()
        self.update_target_filter_list()
        self.stats_panel.refresh()
        # Only auto-select if nothing is currently selected
        if not self.target_combo.get():
            targets = self.data_store.get_all_targets()
            if targets:
                self.target_combo.current(0)
                self.on_target_selected(None)

    def update_target_selector_list(self) -> None:
        """Update the Select Target combobox with all available targets.

        This method preserves the current selection if possible, making it suitable
        for automatic updates during gameplay without disrupting the user.
        Automatically selects the first target if the list changes and no target
        is currently selected.
        """
        targets = self.data_store.get_all_targets()
        self.immunity_panel.update_target_list(targets)

    def update_target_filter_list(self) -> None:
        """Update the target filter combobox with all available targets."""
        targets = self.data_store.get_all_targets()
        self.dps_panel.update_target_filter_options(targets)

    def on_target_selected(self, event) -> None:
        """Handle target selection from combobox."""
        if event:
            event.widget.selection_clear()  # Clear the UI selection highlight
        target = self.target_combo.get()
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
        new_mode_display = self.time_tracking_var.get()
        new_mode = new_mode_display.lower().replace(" ", "_")

        if new_mode == self.dps_service.time_tracking_mode:
            # No actual change
            return

        # Update the service mode
        self.dps_service.set_time_tracking_mode(new_mode)

        self.log_debug(f"First timestamp mode changed to: {new_mode_display}")

        # Only refresh DPS display if still monitoring
        if self.is_monitoring:
            self.dps_panel.refresh()

    def _on_target_filter_changed(self, event: tk.Event) -> None:
        """Handle target filter change from combobox.

        Updates the DPS display to show data for the selected target only.

        Args:
            event: Tkinter event from combobox selection
        """
        event.widget.selection_clear()  # Clear the UI selection highlight
        self.log_debug(f"Target filter changed to: {self.target_filter_var.get()}")

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
        self.queue_processor.process_queue(
            self.data_queue,
            on_log_message=self.log_debug,
            on_dps_updated=self.refresh_dps,
            on_target_selected=self._on_target_details_needed,
            on_immunity_changed=self._on_immunity_changed,
            on_damage_dealt=self._on_damage_dealt,
            debug_enabled=self.debug_panel.get_debug_enabled(),
        )

        # Schedule next check
        self.root.after(100, self.process_queue)

    def _on_target_details_needed(self, target: str) -> None:
        """Callback from queue processor when target details need refresh.

        Args:
            target: Name of target to refresh
        """
        if self.target_combo.get() == target:
            self.immunity_panel.refresh_target_details(target)

    def _on_immunity_changed(self, target: str) -> None:
        """Callback from queue processor when immunity data changes.

        Args:
            target: Name of target with immunity changes
        """
        if self.target_combo.get() == target:
            self.immunity_panel.refresh_display()

    def _on_damage_dealt(self, target: str) -> None:
        """Callback from queue processor when damage is dealt.

        Args:
            target: Name of target that received damage
        """
        # Refresh immunity panel if this is the currently selected target
        # to ensure all damage types are displayed
        if self.target_combo.get() == target:
            self.immunity_panel.refresh_display()

    def on_closing(self) -> None:
        """Handle application closing."""
        if self.is_importing:
            self.import_abort_event.set()
        self.pause_monitoring()
        self.data_store.close()
        self.root.destroy()

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
        self.debug_mode = bool(self.debug_mode_var.get())
        self.log_debug(f"Debug output {'enabled' if self.debug_mode else 'disabled'}")
