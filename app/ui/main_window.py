"""Main application window for Woo's NWN Parser.

This module contains the WoosNwnParserApp class which manages the main
application window, UI components, and event processing.
"""

import queue
from pathlib import Path
from typing import Optional

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

        # Debug mode
        self.debug_mode = False

        # Get the font object defined by the Sun Valley theme to use inside tk non-themed widgets (e.g., tk.Text)
        self.theme_font = font.nametofont("SunValleyBodyFont")

        self.setup_ui()
        self.process_queue()

        # Auto-start monitoring if log directory is available
        if self.log_directory:
            self.root.after(100, self.start_monitoring)


    def setup_ui(self) -> None:
        """Set up the user interface."""
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

        ttk.Button(file_frame, text="Browse...", command=self.browse_directory).pack(side="left", padx=5)

        # Control buttons
        buttons_frame = ttk.Frame(control_frame)
        buttons_frame.pack(fill="x", pady=(5, 0))

        self.start_btn = ttk.Button(buttons_frame, text="Start Monitoring", command=self.start_monitoring)
        self.start_btn.pack(side="left", padx=5)

        self.pause_btn = ttk.Button(buttons_frame, text="Pause Monitoring", command=self.pause_monitoring, state=tk.DISABLED)
        self.pause_btn.pack(side="left", padx=5)

        ttk.Button(buttons_frame, text="Reset Data", command=self.reset_data).pack(side="left", padx=5)
        ttk.Button(buttons_frame, text="Load & Parse Logs", command=self.load_and_parse_directory).pack(side="left", padx=5)

        # Status indicator
        self.status_label = ttk.Label(buttons_frame, text="● Paused", foreground="red")
        self.status_label.pack(side="right", padx=5)

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

            # Enable start button only if not currently monitoring
            if not self.is_monitoring:
                self.start_btn.config(state=tk.NORMAL)

    def load_and_parse_directory(self) -> None:
        """Load and parse all log files in the directory."""
        if not self.log_directory:
            messagebox.showwarning("No Directory", "Please select a log directory first.")
            return

        # Enable debug mode temporarily to show progress
        was_debug_enabled = self.debug_mode
        self.debug_mode = True

        self.log_debug(f"Loading and parsing all files from: {self.log_directory}")

        # Disable UI controls during load
        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.DISABLED)

        try:
            # Clear all existing data once before processing files
            self.data_store.clear_all_data()
            self.parser.target_ac.clear()
            self.parser.target_saves.clear()
            self.parser.target_attack_bonus.clear()

            # Parse all log files in the directory (in order: log1, log2, log3, log4)
            log_dir = Path(self.log_directory)
            log_files = sorted(log_dir.glob('nwclientLog[1-4].txt'))

            if not log_files:
                self.log_debug("No log files found in directory")
            else:
                total_lines = 0
                for log_file in log_files:
                    self.log_debug(f"Parsing: {log_file.name}")
                    result = parse_and_import_file(str(log_file), self.parser, self.data_store)
                    if result['success']:
                        lines = result['lines_processed']
                        total_lines += lines
                        self.log_debug(f"  → {log_file.name}: {lines} lines")
                    else:
                        self.log_debug(f"  → Error: {result['error']}", msg_type='error')

                self.log_debug(f"All files loaded and parsed successfully ({total_lines} total lines)")
        finally:
            # Restore debug mode
            self.debug_mode = was_debug_enabled

            # Re-enable UI controls
            self.start_btn.config(state=tk.NORMAL)
            self.pause_btn.config(state=tk.DISABLED)

            # Refresh all UI elements
            self.refresh_targets()

            # Refresh DPS display with loaded data
            self.dps_panel.refresh()

    def start_monitoring(self) -> None:
        """Start monitoring the log directory for new log files."""
        if not self.log_directory:
            messagebox.showwarning("No Directory", "Please select a log directory first.")
            return

        self.is_monitoring = True
        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.dps_panel.refresh()
        self.status_label.config(text="● Monitoring", foreground="green")

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
        self.start_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED)
        self.status_label.config(text="● Paused", foreground="red")

        # Cancel polling if active
        if self.polling_job:
            self.root.after_cancel(self.polling_job)
            self.polling_job = None

        # Cancel DPS auto-refresh if in Global mode
        if self.dps_refresh_job is not None:
            self.root.after_cancel(self.dps_refresh_job)
            self.dps_refresh_job = None


        self.log_debug("Monitoring paused")

    def poll_log_file(self) -> None:
        """Manually poll the log directory for changes."""
        if self.is_monitoring and self.directory_monitor:
            self.directory_monitor.read_new_lines(self.parser, self.data_queue)
            # Update the active file label
            self.update_active_file_label()
            # Update target lists when new data arrives
            self.refresh_targets()
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

        # Reset DPS service state
        self.dps_service.set_global_start_time(None)

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
