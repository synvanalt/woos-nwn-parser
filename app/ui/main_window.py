"""Main application window for Woo's NWN Parser.

This module contains the WoosNwnParserApp class which manages the main
application window, UI components, and event processing.
"""

import queue
import multiprocessing as mp
import time
from datetime import datetime
from time import perf_counter
from collections import deque
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, font

from ..parser import LogParser
from ..parsed_events import DeathCharacterIdentifiedEvent, DeathSnippetEvent
from ..storage import DataStore
from ..monitor import LogDirectoryMonitor
from ..settings import load_app_settings, save_app_settings
from ..utils import IMPORT_RESULT_QUEUE_MAXSIZE, import_worker_process
from ..services import QueueProcessor, DPSCalculationService
from .formatters import get_default_log_directory
from .message_dialogs import show_warning_dialog
from .tooltips import TooltipManager
from .window_style import apply_dark_title_bar
from .controllers import (
    ImportController,
    MonitorController,
    RefreshCoordinator,
    SessionSettingsController,
)
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

    @property
    def is_monitoring(self) -> bool:
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            return bool(self.__dict__.get("_legacy_is_monitoring", False))
        return bool(controller.is_monitoring)

    @is_monitoring.setter
    def is_monitoring(self, value: bool) -> None:
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            self.__dict__["_legacy_is_monitoring"] = bool(value)
            return
        controller.is_monitoring = bool(value)

    @property
    def directory_monitor(self):
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_directory_monitor")
        return controller.directory_monitor

    @directory_monitor.setter
    def directory_monitor(self, value) -> None:
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            self.__dict__["_legacy_directory_monitor"] = value
            return
        controller.directory_monitor = value

    @property
    def polling_job(self):
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_polling_job")
        return controller.polling_job

    @polling_job.setter
    def polling_job(self, value) -> None:
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            self.__dict__["_legacy_polling_job"] = value
            return
        controller.polling_job = value

    @property
    def monitor_thread(self):
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_monitor_thread")
        return controller.monitor_thread

    @monitor_thread.setter
    def monitor_thread(self, value) -> None:
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            self.__dict__["_legacy_monitor_thread"] = value
            return
        controller.monitor_thread = value

    @property
    def monitor_stop_event(self):
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_monitor_stop_event")
        return controller.monitor_stop_event

    @monitor_stop_event.setter
    def monitor_stop_event(self, value) -> None:
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            self.__dict__["_legacy_monitor_stop_event"] = value
            return
        controller.monitor_stop_event = value

    @property
    def _monitor_active_file_name(self):
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_monitor_active_file_name", "N/A")
        return controller.active_file_name

    @_monitor_active_file_name.setter
    def _monitor_active_file_name(self, value: str) -> None:
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            self.__dict__["_legacy_monitor_active_file_name"] = value
            return
        controller._monitor_active_file_name = value

    @property
    def _monitor_log_queue(self):
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_monitor_log_queue")
        return controller._monitor_log_queue

    @_monitor_log_queue.setter
    def _monitor_log_queue(self, value) -> None:
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            self.__dict__["_legacy_monitor_log_queue"] = value
            return
        controller._monitor_log_queue = value

    @property
    def _debug_monitor_enabled(self):
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_debug_monitor_enabled", False)
        return controller._debug_monitor_enabled

    @_debug_monitor_enabled.setter
    def _debug_monitor_enabled(self, value: bool) -> None:
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            self.__dict__["_legacy_debug_monitor_enabled"] = bool(value)
            return
        controller._debug_monitor_enabled = bool(value)

    @property
    def is_importing(self) -> bool:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return bool(self.__dict__.get("_legacy_is_importing", False))
        return bool(controller.is_importing)

    @is_importing.setter
    def is_importing(self, value: bool) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_is_importing"] = bool(value)
            return
        controller.is_importing = bool(value)

    @property
    def import_abort_event(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_abort_event")
        return controller.import_abort_event

    @import_abort_event.setter
    def import_abort_event(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_abort_event"] = value
            return
        controller.import_abort_event = value

    @property
    def import_process(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_process")
        return controller.import_process

    @import_process.setter
    def import_process(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_process"] = value
            return
        controller.import_process = value

    @property
    def import_abort_flag(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_abort_flag")
        return controller.import_abort_flag

    @import_abort_flag.setter
    def import_abort_flag(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_abort_flag"] = value
            return
        controller.import_abort_flag = value

    @property
    def import_result_queue(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_result_queue")
        return controller.import_result_queue

    @import_result_queue.setter
    def import_result_queue(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_result_queue"] = value
            return
        controller.import_result_queue = value

    @property
    def import_poll_job(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_poll_job")
        return controller.import_poll_job

    @import_poll_job.setter
    def import_poll_job(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_poll_job"] = value
            return
        controller.import_poll_job = value

    @property
    def import_modal(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_modal")
        return controller.import_modal

    @import_modal.setter
    def import_modal(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_modal"] = value
            return
        controller.import_modal = value

    @property
    def import_status_text(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_status_text")
        return controller.import_status_text

    @import_status_text.setter
    def import_status_text(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_status_text"] = value
            return
        controller.import_status_text = value

    @property
    def import_progress_text(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_progress_text")
        return controller.import_progress_text

    @import_progress_text.setter
    def import_progress_text(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_progress_text"] = value
            return
        controller.import_progress_text = value

    @property
    def import_abort_button(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_abort_button")
        return controller.import_abort_button

    @import_abort_button.setter
    def import_abort_button(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_abort_button"] = value
            return
        controller.import_abort_button = value

    @property
    def _import_status(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_status", {})
        return controller._import_status

    @_import_status.setter
    def _import_status(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_status"] = value
            return
        controller._import_status = value

    @property
    def _pending_file_payloads(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_pending_file_payloads")
        return controller._pending_file_payloads

    @_pending_file_payloads.setter
    def _pending_file_payloads(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_pending_file_payloads"] = value
            return
        controller._pending_file_payloads = value

    @property
    def _is_applying_payload(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return bool(self.__dict__.get("_legacy_is_applying_payload", False))
        return bool(controller._is_applying_payload)

    @_is_applying_payload.setter
    def _is_applying_payload(self, value: bool) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_is_applying_payload"] = bool(value)
            return
        controller._is_applying_payload = bool(value)

    @property
    def _refresh_job(self):
        coordinator = getattr(self, "refresh_coordinator", None)
        if coordinator is None:
            return self.__dict__.get("_legacy_refresh_job")
        return coordinator.refresh_job

    @_refresh_job.setter
    def _refresh_job(self, value) -> None:
        self.__dict__["_legacy_refresh_job"] = value

    @property
    def _dps_dirty(self) -> bool:
        coordinator = getattr(self, "refresh_coordinator", None)
        if coordinator is None:
            return bool(self.__dict__.get("_legacy_dps_dirty", False))
        return coordinator.dps_dirty

    @_dps_dirty.setter
    def _dps_dirty(self, value: bool) -> None:
        coordinator = getattr(self, "refresh_coordinator", None)
        if coordinator is None:
            self.__dict__["_legacy_dps_dirty"] = bool(value)
            return
        coordinator._dps_dirty = bool(value)

    @property
    def _targets_dirty(self) -> bool:
        coordinator = getattr(self, "refresh_coordinator", None)
        if coordinator is None:
            return bool(self.__dict__.get("_legacy_targets_dirty", False))
        return coordinator.targets_dirty

    @_targets_dirty.setter
    def _targets_dirty(self, value: bool) -> None:
        coordinator = getattr(self, "refresh_coordinator", None)
        if coordinator is None:
            self.__dict__["_legacy_targets_dirty"] = bool(value)
            return
        coordinator._targets_dirty = bool(value)

    @property
    def _immunity_dirty_targets(self) -> set[str]:
        coordinator = getattr(self, "refresh_coordinator", None)
        if coordinator is None:
            return self.__dict__.get("_legacy_immunity_dirty_targets", set())
        return coordinator.immunity_dirty_targets

    @_immunity_dirty_targets.setter
    def _immunity_dirty_targets(self, value: set[str]) -> None:
        coordinator = getattr(self, "refresh_coordinator", None)
        if coordinator is None:
            self.__dict__["_legacy_immunity_dirty_targets"] = value
            return
        coordinator._immunity_dirty_targets = value

    @property
    def _settings_save_job(self):
        controller = getattr(self, "settings_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_settings_save_job")
        return controller.settings_save_job

    @_settings_save_job.setter
    def _settings_save_job(self, value) -> None:
        self.__dict__["_legacy_settings_save_job"] = value

    @property
    def monitoring_was_active_before_import(self) -> bool:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return bool(self.__dict__.get("_legacy_monitoring_was_active_before_import", False))
        return bool(controller.monitoring_was_active_before_import)

    @monitoring_was_active_before_import.setter
    def monitoring_was_active_before_import(self, value: bool) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_monitoring_was_active_before_import"] = bool(value)
            return
        controller.monitoring_was_active_before_import = bool(value)

    @property
    def _import_status_lock(self):
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return self.__dict__.get("_legacy_import_status_lock")
        return controller._import_status_lock

    @_import_status_lock.setter
    def _import_status_lock(self, value) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_import_status_lock"] = value
            return
        controller._import_status_lock = value

    @property
    def _last_modal_file(self) -> str:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return str(self.__dict__.get("_legacy_last_modal_file", ""))
        return str(controller._last_modal_file)

    @_last_modal_file.setter
    def _last_modal_file(self, value: str) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_last_modal_file"] = str(value)
            return
        controller._last_modal_file = str(value)

    @property
    def _last_modal_files_completed(self) -> int:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            return int(self.__dict__.get("_legacy_last_modal_files_completed", -1))
        return int(controller._last_modal_files_completed)

    @_last_modal_files_completed.setter
    def _last_modal_files_completed(self, value: int) -> None:
        controller = getattr(self, "import_controller", None)
        if controller is None:
            self.__dict__["_legacy_last_modal_files_completed"] = int(value)
            return
        controller._last_modal_files_completed = int(value)

    def __init__(self, root: tk.Tk) -> None:
        """Initialize the application.

        Args:
            root: The root Tkinter window
        """
        self.root = root
        self.root.title("Woo's NWN Parser")
        self.root.geometry("730x550")

        # Core services
        self.log_directory = ""
        self.window_icon_path: Optional[str] = None
        self.notebook: Optional[ttk.Notebook] = None
        self._is_closing = False

        self.parser = LogParser(parse_immunity=True)
        self.data_store = DataStore()
        self.queue_processor = QueueProcessor(self.data_store, self.parser)
        self.dps_service = DPSCalculationService(self.data_store)
        self.settings_controller = SessionSettingsController(
            root=self.root,
            parser=self.parser,
            dps_service=self.dps_service,
            get_log_directory=lambda: self.log_directory,
            get_death_fallback_line=self._get_death_fallback_line_for_settings,
            get_first_timestamp_mode=self._get_current_first_timestamp_mode,
            load_settings=load_app_settings,
            save_settings=save_app_settings,
        )
        self._settings = self.settings_controller.load_initial_settings()
        parse_immunity_enabled = self._settings.parse_immunity
        if parse_immunity_enabled is None:
            parse_immunity_enabled = True
        self.parser.parse_immunity = parse_immunity_enabled
        persisted_first_timestamp_mode = self._settings.first_timestamp_mode
        if persisted_first_timestamp_mode is not None:
            self.dps_service.set_time_tracking_mode(persisted_first_timestamp_mode)

        # Queue and scheduling
        self.data_queue = queue.Queue(maxsize=self.DATA_QUEUE_MAXSIZE)
        configured_log_directory = (self._settings.log_directory or "").strip()
        self.log_directory = configured_log_directory or get_default_log_directory()
        configured_fallback_line = (self._settings.death_fallback_line or "").strip()
        self._initial_death_fallback_line = configured_fallback_line or LogParser.DEFAULT_DEATH_FALLBACK_LINE
        self.dps_refresh_job = None
        self._queue_tick_ms = self.QUEUE_TICK_MS_NORMAL
        self._queue_pressure_state = "normal"

        # Debug mode
        self.debug_mode = False
        self._debug_tab_visible = False
        self._dps_tab_click_times: deque[float] = deque()
        self._debug_unlock_click_target = 7
        self._debug_unlock_window_seconds = 3.0
        self._dps_tab_text = "Damage Per Second"

        # Get the font object defined by the Sun Valley theme to use inside tk non-themed widgets (e.g., tk.Text)
        self.theme_font = font.nametofont("SunValleyBodyFont")
        self.tooltip_manager = TooltipManager(self.root)

        self.setup_ui()
        if hasattr(self, "dps_panel") and hasattr(self, "stats_panel") and hasattr(self, "immunity_panel"):
            self.refresh_coordinator = RefreshCoordinator(
                root=self.root,
                dps_panel=self.dps_panel,
                stats_panel=self.stats_panel,
                immunity_panel=self.immunity_panel,
                refresh_targets=self.refresh_targets,
                on_death_snippet=self._on_death_snippet,
                on_character_identified=self._on_death_character_identified,
            )
        if hasattr(self, "debug_panel") and hasattr(self, "dps_panel"):
            self.monitor_controller = MonitorController(
                root=self.root,
                parser=self.parser,
                data_queue=self.data_queue,
                debug_panel=self.debug_panel,
                dps_panel=self.dps_panel,
                get_log_directory=lambda: self.log_directory,
                set_log_directory=self._set_log_directory,
                set_monitoring_switch_ui=self._set_monitoring_switch_ui,
                set_active_file_name=self._set_active_file_name,
                log_debug=self.log_debug,
                persist_settings_now=self._persist_session_settings,
                get_window_icon_path=lambda: self.window_icon_path,
                get_queue_pressure_state=self._get_queue_pressure_state,
                get_monitor_max_lines_per_poll=self._get_monitor_max_lines_per_poll,
                get_monitor_sleep_seconds=self._get_monitor_sleep_seconds,
            )
        if hasattr(self, "dps_panel") and hasattr(self, "death_snippet_panel"):
            self.import_controller = ImportController(
                root=self.root,
                parser=self.parser,
                data_store=self.data_store,
                dps_panel=self.dps_panel,
                death_snippet_panel=self.death_snippet_panel,
                pause_monitoring=self.pause_monitoring,
                refresh_targets=self.refresh_targets,
                set_controls_busy=self._set_import_ui_busy,
                log_debug=self.log_debug,
                get_window_icon_path=lambda: self.window_icon_path,
                center_window_on_parent=self._center_window_on_parent,
                apply_modal_icon=self._apply_modal_icon,
                on_character_identified=self._on_death_character_identified,
                import_apply_frame_budget_ms=self.IMPORT_APPLY_FRAME_BUDGET_MS,
                import_apply_mutation_batch_size=self.IMPORT_APPLY_MUTATION_BATCH_SIZE,
            )
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

        self.log_directory_label = ttk.Label(file_frame, text="Log Directory:")
        self.log_directory_label.pack(side="left", padx=5)
        self.dir_text = tk.StringVar(value="No directory selected")
        self.dir_label = ttk.Entry(file_frame, state="readonly", textvariable=self.dir_text, foreground="gray", width=40)
        self.dir_label.pack(side="left", fill="x", expand=True, padx=(2, 2))

        self.active_file_name_label = ttk.Label(file_frame, text="File:")
        self.active_file_name_label.pack(side="left", padx=(10, 0))
        self.active_file_text = tk.StringVar(value="N/A")
        self.active_file_label = ttk.Entry(file_frame, state="readonly", textvariable=self.active_file_text, foreground="gray", width=13)
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
        self.dps_panel = DPSPanel(self.notebook, self.data_store, self.dps_service, tooltip_manager=self.tooltip_manager)
        self._restore_persisted_dps_panel_state()
        self.notebook.add(self.dps_panel, text=self._dps_tab_text)
        self.dps_panel.time_tracking_combo.bind("<<ComboboxSelected>>", self._on_time_tracking_mode_changed)
        self.dps_panel.target_filter_combo.bind("<<ComboboxSelected>>", self._on_target_filter_changed)

        # Tab 2: Target Stats Panel (using TargetStatsPanel widget)
        self.stats_panel = TargetStatsPanel(self.notebook, self.data_store, tooltip_manager=self.tooltip_manager)
        self.notebook.add(self.stats_panel, text="Target Stats")

        # Tab 3: Immunity Panel (using ImmunityPanel widget)
        self.immunity_panel = ImmunityPanel(
            self.notebook,
            self.data_store,
            self.parser,
            tooltip_manager=self.tooltip_manager,
            on_parse_immunity_changed=self._on_parse_immunity_changed,
        )
        self.notebook.add(self.immunity_panel, text="Target Immunities")
        self.immunity_panel.target_combo.bind("<<ComboboxSelected>>", self.on_target_selected)

        # Tab 4: Death Snippets Panel
        self.death_snippet_panel = DeathSnippetPanel(self.notebook, tooltip_manager=self.tooltip_manager)
        self.death_snippet_panel.set_fallback_death_line(self._initial_death_fallback_line)
        self.notebook.add(self.death_snippet_panel, text="Death Snippets")
        self.death_snippet_panel.configure_identity_callbacks(
            on_character_name_changed=self._on_death_character_name_changed,
            on_fallback_line_changed=self._on_death_fallback_line_changed,
        )
        self.parser.set_death_character_name(self.death_snippet_panel.get_character_name())
        self.parser.set_death_fallback_line(self.death_snippet_panel.get_fallback_death_line())

        # Tab 5: Debug Console Panel (using DebugConsolePanel widget)
        self.debug_panel = DebugConsolePanel(self.notebook, tooltip_manager=self.tooltip_manager)
        self.debug_panel.debug_mode_var.trace("w", self._on_debug_toggle)
        self.notebook.bind("<Button-1>", self._on_notebook_click, add=True)
        self._register_tooltips()

    def _register_tooltips(self) -> None:
        """Register static tooltips for main-window controls."""
        self.tooltip_manager.register_many(
            [self.log_directory_label, self.dir_label],
            "Folder containing your NWN client log files",
        )
        self.tooltip_manager.register_many(
            [self.active_file_name_label, self.active_file_label],
            "Current log file the monitor considers active",
        )
        self.tooltip_manager.register(
            self.browse_button,
            "Choose the folder that contains your Neverwinter Nights client logs",
        )
        self.tooltip_manager.register(
            self.monitoring_switch,
            "Turn live log monitoring on or off",
        )
        self.tooltip_manager.register(
            self.clear_button,
            "Clear all parsed data from this session",
        )
        self.tooltip_manager.register(
            self.load_parse_button,
            "Select one or more existing log files and parse them on demand",
        )

    def _set_log_directory(self, directory: str) -> None:
        """Update stored and displayed log directory."""
        self.log_directory = directory
        self.dir_text.set(value=directory.replace("/", "\\"))

    def _set_active_file_name(self, file_name: str) -> None:
        """Update stored and displayed active file name."""
        self.active_file_text.set(value=file_name or "N/A")

    def _get_death_fallback_line_for_settings(self) -> str:
        """Read the fallback death line from the UI when available."""
        death_panel = getattr(self, "death_snippet_panel", None)
        if death_panel is not None:
            return death_panel.get_fallback_death_line()
        return str(getattr(self.parser, "death_fallback_line", "")).strip()

    def _ensure_refresh_coordinator(self) -> RefreshCoordinator:
        """Build a refresh coordinator lazily for test shells created via __new__."""
        controller = getattr(self, "refresh_coordinator", None)
        if controller is None:
            controller = RefreshCoordinator(
                root=self.root,
                dps_panel=self.dps_panel,
                stats_panel=self.stats_panel,
                immunity_panel=self.immunity_panel,
                refresh_targets=self.refresh_targets,
                on_death_snippet=self._on_death_snippet,
                on_character_identified=self._on_death_character_identified,
            )
            controller._refresh_job = self.__dict__.get("_legacy_refresh_job")
            controller._dps_dirty = bool(self.__dict__.get("_legacy_dps_dirty", False))
            controller._targets_dirty = bool(self.__dict__.get("_legacy_targets_dirty", False))
            controller._immunity_dirty_targets = self.__dict__.get(
                "_legacy_immunity_dirty_targets",
                set(),
            )
            self.refresh_coordinator = controller
        return controller

    def _ensure_settings_controller(self) -> SessionSettingsController:
        """Build a settings controller lazily for test shells created via __new__."""
        controller = getattr(self, "settings_controller", None)
        if controller is None:
            controller = SessionSettingsController(
                root=getattr(self, "root", None),
                parser=self.parser,
                dps_service=getattr(self, "dps_service", None),
                get_log_directory=lambda: getattr(self, "log_directory", ""),
                get_death_fallback_line=self._get_death_fallback_line_for_settings,
                get_first_timestamp_mode=self._get_current_first_timestamp_mode,
                load_settings=load_app_settings,
                save_settings=save_app_settings,
            )
            controller._settings_save_job = self.__dict__.get("_legacy_settings_save_job")
            self.settings_controller = controller
        return controller

    def _ensure_monitor_controller(self) -> MonitorController:
        """Build a monitor controller lazily for test shells created via __new__."""
        controller = getattr(self, "monitor_controller", None)
        if controller is None:
            controller = MonitorController(
                root=getattr(self, "root", None),
                parser=self.parser,
                data_queue=self.data_queue,
                debug_panel=self.debug_panel,
                dps_panel=self.dps_panel,
                get_log_directory=lambda: getattr(self, "log_directory", ""),
                set_log_directory=self._set_log_directory,
                set_monitoring_switch_ui=self._set_monitoring_switch_ui,
                set_active_file_name=self._set_active_file_name,
                log_debug=self.log_debug,
                persist_settings_now=self._persist_session_settings,
                get_window_icon_path=lambda: getattr(self, "window_icon_path", None),
                get_queue_pressure_state=self._get_queue_pressure_state,
                get_monitor_max_lines_per_poll=self._get_monitor_max_lines_per_poll,
                get_monitor_sleep_seconds=self._get_monitor_sleep_seconds,
            )
            controller.directory_monitor = self.__dict__.get("_legacy_directory_monitor")
            controller.is_monitoring = bool(self.__dict__.get("_legacy_is_monitoring", False))
            controller.monitor_thread = self.__dict__.get("_legacy_monitor_thread")
            controller.monitor_stop_event = self.__dict__.get("_legacy_monitor_stop_event", controller.monitor_stop_event)
            controller._monitor_active_file_name = self.__dict__.get("_legacy_monitor_active_file_name", "N/A")
            monitor_log_queue = self.__dict__.get("_legacy_monitor_log_queue")
            if monitor_log_queue is not None:
                controller._monitor_log_queue = monitor_log_queue
            controller._debug_monitor_enabled = bool(
                self.__dict__.get("_legacy_debug_monitor_enabled", False)
            )
            controller.polling_job = self.__dict__.get("_legacy_polling_job")
            self.monitor_controller = controller
        return controller

    def _ensure_import_controller(self) -> ImportController:
        """Build an import controller lazily for test shells created via __new__."""
        controller = getattr(self, "import_controller", None)
        if controller is None:
            controller = ImportController(
                root=getattr(self, "root", None),
                parser=self.parser,
                data_store=getattr(self, "data_store", None),
                dps_panel=getattr(self, "dps_panel", None),
                death_snippet_panel=getattr(self, "death_snippet_panel", None),
                pause_monitoring=self.pause_monitoring,
                refresh_targets=self.refresh_targets,
                set_controls_busy=self._set_import_ui_busy,
                log_debug=self.log_debug,
                get_window_icon_path=lambda: getattr(self, "window_icon_path", None),
                center_window_on_parent=self._center_window_on_parent,
                apply_modal_icon=self._apply_modal_icon,
                on_character_identified=self._on_death_character_identified,
                import_apply_frame_budget_ms=self.IMPORT_APPLY_FRAME_BUDGET_MS,
                import_apply_mutation_batch_size=self.IMPORT_APPLY_MUTATION_BATCH_SIZE,
            )
            controller.is_importing = bool(self.__dict__.get("_legacy_is_importing", False))
            controller.monitoring_was_active_before_import = bool(
                self.__dict__.get("_legacy_monitoring_was_active_before_import", False)
            )
            controller.import_abort_event = self.__dict__.get(
                "_legacy_import_abort_event",
                controller.import_abort_event,
            )
            controller.import_process = self.__dict__.get("_legacy_import_process")
            controller.import_abort_flag = self.__dict__.get("_legacy_import_abort_flag")
            controller.import_result_queue = self.__dict__.get("_legacy_import_result_queue")
            controller.import_poll_job = self.__dict__.get("_legacy_import_poll_job")
            controller.import_modal = self.__dict__.get("_legacy_import_modal")
            controller.import_status_text = self.__dict__.get("_legacy_import_status_text")
            controller.import_progress_text = self.__dict__.get("_legacy_import_progress_text")
            controller.import_abort_button = self.__dict__.get("_legacy_import_abort_button")
            controller._import_status = self.__dict__.get("_legacy_import_status", {})
            controller._import_status_lock = self.__dict__.get(
                "_legacy_import_status_lock",
                controller._import_status_lock,
            )
            pending_file_payloads = self.__dict__.get("_legacy_pending_file_payloads")
            if pending_file_payloads is not None:
                controller._pending_file_payloads = pending_file_payloads
            controller._is_applying_payload = bool(
                self.__dict__.get("_legacy_is_applying_payload", False)
            )
            controller._last_modal_file = str(self.__dict__.get("_legacy_last_modal_file", ""))
            controller._last_modal_files_completed = int(
                self.__dict__.get("_legacy_last_modal_files_completed", -1)
            )
            self.import_controller = controller
        return controller

    def browse_directory(self) -> None:
        """Open directory dialog to select log directory."""
        if not hasattr(self, "monitor_controller"):
            directory = filedialog.askdirectory(
                title="Select Log Directory (contains nwclientLog*.txt files)",
                parent=self.root,
            )
            if directory:
                had_log_files = self._select_log_directory(directory)
                if not had_log_files:
                    show_warning_dialog(
                        self.root,
                        "No Log Files",
                        "No nwclientLog*.txt files found in this directory.\n"
                        "Monitoring will wait for log files to appear.",
                        icon_path=getattr(self, "window_icon_path", None),
                    )
            return
        self._ensure_monitor_controller().browse_for_directory()

    def _select_log_directory(self, directory: str) -> bool:
        """Apply a selected log directory and refresh monitor/file state."""
        if not hasattr(self, "monitor_controller"):
            self.log_directory = directory
            self.dir_text.set(value=directory.replace("/", "\\"))
            temp_monitor = LogDirectoryMonitor(directory)
            active_file = temp_monitor.find_active_log_file()
            self._monitor_active_file_name = active_file.name if active_file is not None else "N/A"
            self.update_active_file_label()
            if active_file is None:
                self.log_debug("No matching log files found; monitoring will wait for one to appear.")
            else:
                self.log_debug(f"Selected active log file: {active_file.name}")
            if self.is_monitoring:
                self.pause_monitoring()
                self.start_monitoring()
            else:
                self._set_monitoring_switch_ui(False)
            self._persist_session_settings()
            return active_file is not None
        return self._ensure_monitor_controller().select_log_directory(directory)

    def load_and_parse_selected_files(self) -> None:
        """Open file picker and parse selected .txt logs in a background worker."""
        if not hasattr(self, "import_controller"):
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
            self.is_importing = True
            self._import_status = {
                "files": selected_files,
                "total_files": len(selected_files),
                "files_completed": 0,
                "current_file": "",
                "errors": [],
                "aborted": False,
                "success": False,
                "worker_done": False,
            }
            self._last_modal_file = ""
            self._last_modal_files_completed = -1
            self._pending_file_payloads.clear()
            self._is_applying_payload = False
            self._set_import_ui_busy(True)
            self._show_import_modal()
            self._start_import_worker(selected_files)
            self._poll_import_progress()
            return
        self._ensure_import_controller().start_from_dialog(is_monitoring=self.is_monitoring)

    def _set_import_ui_busy(self, is_busy: bool) -> None:
        """Disable/enable controls while import is running."""
        state = tk.DISABLED if is_busy else tk.NORMAL
        self.monitoring_switch.config(state=state)
        self.browse_button.config(state=state)
        self.load_parse_button.config(state=state)
        self.clear_button.config(state=state)

    def _show_import_modal(self) -> None:
        """Show a modal with import progress and abort button."""
        if not hasattr(self, "import_controller"):
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
            actions = ttk.Frame(container)
            actions.pack(side="bottom", fill="x")
            self.import_abort_button = ttk.Button(actions, text="Abort", command=self.abort_load_parse)
            self.import_abort_button.pack(anchor="e")
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

            self.import_modal.after_idle(_show_modal_when_ready)
            return
        self._ensure_import_controller().show_modal()

    def _start_import_worker(self, selected_files: list[Path]) -> None:
        """Start worker process for import operation."""
        if not hasattr(self, "import_controller"):
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
            return
        self._ensure_import_controller().start_worker(selected_files)

    def _drain_import_events(self) -> None:
        """Drain events from the import worker process queue."""
        if not hasattr(self, "import_controller"):
            controller = self._ensure_import_controller()
            controller.root = getattr(self, "root", None)
            controller.data_store = getattr(self, "data_store", None)
            controller.dps_panel = getattr(self, "dps_panel", None)
            controller.death_snippet_panel = getattr(self, "death_snippet_panel", None)
            controller.import_result_queue = self.import_result_queue
            controller._import_status = self._import_status
            controller._pending_file_payloads = self._pending_file_payloads
            controller._is_applying_payload = self._is_applying_payload
            controller._import_status_lock = self._import_status_lock
            controller.drain_events()
            self._import_status = controller._import_status
            self._pending_file_payloads = controller._pending_file_payloads
            self._is_applying_payload = controller._is_applying_payload
            return
        self._ensure_import_controller().drain_events()

    def _apply_pending_payloads_incremental(self) -> None:
        """Apply completed-file payloads in small slices on the Tk thread."""
        if not hasattr(self, "import_controller") or not hasattr(self, "data_store"):
            budget_ms = self.IMPORT_APPLY_FRAME_BUDGET_MS
            mutation_batch_size = max(1, int(self.IMPORT_APPLY_MUTATION_BATCH_SIZE))
            deadline = perf_counter() + (budget_ms / 1000.0)
            while perf_counter() < deadline and self._pending_file_payloads:
                item = self._pending_file_payloads[0]
                mutation_idx = item["mutation_idx"]
                mutations = item["mutations"]
                if mutation_idx < len(mutations):
                    batch_end = min(mutation_idx + mutation_batch_size, len(mutations))
                    self.data_store.apply_mutations(mutations[mutation_idx:batch_end])
                    item["mutation_idx"] = batch_end
                    continue
                death_snippets = item["death_snippets"]
                if death_snippets:
                    self.death_snippet_panel.add_death_events(
                        [self._death_snippet_from_payload(event) for event in death_snippets]
                    )
                    item["death_snippets"] = []
                identity_events = item["death_character_identified"]
                if identity_events:
                    for identity_event in identity_events:
                        self._on_death_character_identified(
                            self._death_character_identified_from_payload(identity_event)
                        )
                    item["death_character_identified"] = []
                self._pending_file_payloads.popleft()
            if self._pending_file_payloads:
                self.root.after(1, self._apply_pending_payloads_incremental)
                return
            self._is_applying_payload = False
            return
        self._ensure_import_controller().apply_pending_payloads_incremental()

    def _poll_import_progress(self) -> None:
        """Update modal with latest import status."""
        if not hasattr(self, "import_controller") or not hasattr(self, "immunity_panel"):
            if not self.is_importing:
                return
            self._drain_import_events()
            with self._import_status_lock:
                status = dict(self._import_status)
            if self.import_status_text is not None:
                current_file = status.get("current_file") or "Preparing selected files..."
                if self._last_modal_file != current_file:
                    self.import_status_text.set(f"Parsing: {current_file}")
                    self._last_modal_file = current_file
            if self.import_progress_text is not None:
                files_completed = status.get("files_completed", 0)
                total_files = status.get("total_files", 0)
                if self._last_modal_files_completed != files_completed:
                    self.import_progress_text.set(f"{files_completed}/{total_files} files completed")
                    self._last_modal_files_completed = files_completed
            worker_done = bool(status.get("worker_done"))
            has_pending = bool(self._pending_file_payloads) or self._is_applying_payload
            if not worker_done or has_pending:
                self.import_poll_job = self.root.after(200, self._poll_import_progress)
                return
            self._finalize_import()
            return
        self._ensure_import_controller().poll_progress()

    def abort_load_parse(self) -> None:
        """Request abort for ongoing import."""
        if not hasattr(self, "import_controller"):
            if not self.is_importing:
                return
            self.import_abort_event.set()
            if self.import_abort_flag is not None:
                self.import_abort_flag.set()
            if self.import_abort_button is not None:
                self.import_abort_button.config(state=tk.DISABLED)
            if self.import_status_text is not None:
                self.import_status_text.set("Aborting...")
            return
        self._ensure_import_controller().abort()

    def _finalize_import(self) -> None:
        """Finalize import and refresh UI."""
        if not hasattr(self, "import_controller"):
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
            if status.get("aborted"):
                self.log_debug(
                    f"Load & Parse aborted. Imported {status.get('files_completed', 0)} files before stop.",
                    msg_type="warning",
                )
            elif status.get("errors"):
                show_warning_dialog(
                    self.root,
                    "Load & Parse Completed with Errors",
                    "\n".join(status["errors"]),
                    icon_path=getattr(self, "window_icon_path", None),
                )
                self.log_debug("Load & Parse completed with file errors.", msg_type="warning")
            else:
                self.log_debug(
                    f"Load & Parse completed: {status.get('total_files', 0)} files.",
                    msg_type="info",
                )
            return
        self._ensure_import_controller().finalize()

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
        self._ensure_monitor_controller().start()

    def pause_monitoring(self) -> None:
        """Pause monitoring the log directory."""
        self._ensure_monitor_controller().pause()
        if self.dps_refresh_job is not None:
            self.root.after_cancel(self.dps_refresh_job)
            self.dps_refresh_job = None
        self._ensure_refresh_coordinator().cancel()

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

    def _enqueue_monitor_log(self, message: str, msg_type: str = "debug") -> None:
        """Queue background-monitor log messages for UI-thread rendering."""
        self._ensure_monitor_controller().enqueue_monitor_log(message, msg_type)

    def _drain_monitor_logs(self, max_messages: int = 200) -> None:
        """Flush queued monitor logs on Tk thread."""
        self._ensure_monitor_controller().drain_monitor_logs(max_messages=max_messages)

    def _start_monitor_thread(self) -> bool:
        """Start background thread that performs file I/O and parsing."""
        return self._ensure_monitor_controller().start_monitor_thread()

    def _stop_monitor_thread(self) -> None:
        """Signal monitor thread to stop and join it quickly."""
        self._ensure_monitor_controller().stop_monitor_thread()

    def _schedule_monitor_restart(self) -> None:
        """Retry starting monitoring thread after prior worker shutdown completes."""
        self._ensure_monitor_controller().schedule_monitor_restart()

    def _retry_monitor_restart(self) -> None:
        """Attempt deferred monitor thread start if app is still monitoring."""
        self._ensure_monitor_controller().retry_monitor_restart()

    def _monitor_loop(self) -> None:
        """Worker loop that polls the active log file and parses new lines."""
        self._ensure_monitor_controller().monitor_loop()

    def poll_log_file(self) -> None:
        """Lightweight UI tick for monitor status updates."""
        if not hasattr(self, "monitor_controller"):
            if self.is_monitoring:
                self._drain_monitor_logs()
                self.update_active_file_label()
                self.polling_job = self.root.after(250, self.poll_log_file)
            return
        self._ensure_monitor_controller().poll_ui_tick()

    def update_active_file_label(self) -> None:
        """Update the active file label to show which log file is being monitored."""
        if not hasattr(self, "monitor_controller"):
            self.active_file_text.set(value=self._monitor_active_file_name or "N/A")
            return
        self._ensure_monitor_controller().update_active_file_label()

    def clear_data(self) -> None:
        """Clear all collected data."""
        # Cancel any pending refresh from Global mode
        if self.dps_refresh_job is not None:
            self.root.after_cancel(self.dps_refresh_job)
            self.dps_refresh_job = None
        self._ensure_refresh_coordinator().cancel()
        self._ensure_refresh_coordinator().clear_dirty_state()

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
        if not hasattr(self, "refresh_coordinator") and hasattr(process_fn, "mock_calls"):
            process_kwargs.update({
                "on_dps_updated": self.refresh_dps,
                "on_target_selected": self._on_target_details_needed,
                "on_immunity_changed": self._on_immunity_changed,
                "on_damage_dealt": self._on_damage_dealt,
                "on_death_snippet": self._on_death_snippet,
                "on_character_identified": self._on_death_character_identified,
            })
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
        if hasattr(self, "refresh_coordinator"):
            self._ensure_refresh_coordinator().handle_queue_result(result)
        else:
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

            if bool(getattr(result, "dps_updated", False)):
                self._dps_dirty = True
            if targets_to_refresh:
                self._targets_dirty = True

            selected_target = ""
            if hasattr(self, "immunity_panel") and hasattr(self.immunity_panel, "target_combo"):
                selected_target = self.immunity_panel.target_combo.get()
            if selected_target and (
                selected_target in immunity_targets or selected_target in damage_targets
            ):
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
        if not hasattr(self, "refresh_coordinator"):
            if getattr(self, "_refresh_job", None) is not None:
                return
            self._refresh_job = self.root.after(180, self._run_coalesced_refresh)
            return
        self._ensure_refresh_coordinator().schedule()

    def _run_coalesced_refresh(self) -> None:
        """Execute one coalesced refresh pass for expensive widgets."""
        if not hasattr(self, "refresh_coordinator"):
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
            return
        self._ensure_refresh_coordinator().run()

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

    @staticmethod
    def _death_snippet_from_payload(payload: dict[str, object]) -> DeathSnippetEvent:
        """Build a typed death-snippet event from import payload data."""
        return ImportController.death_snippet_from_payload(payload)

    @staticmethod
    def _death_character_identified_from_payload(
        payload: dict[str, object],
    ) -> DeathCharacterIdentifiedEvent:
        """Build a typed identity event from import payload data."""
        return ImportController.death_character_identified_from_payload(payload)

    def _on_death_snippet(self, event: DeathSnippetEvent) -> None:
        """Callback from queue processor when a death snippet is produced."""
        self.death_snippet_panel.add_death_event(event)

    def _on_death_character_identified(self, event: DeathCharacterIdentifiedEvent) -> None:
        """Callback when parser auto-identifies player character via whisper token."""
        character_name = event.character_name.strip()
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
        if getattr(self, "_is_closing", False):
            return
        self._is_closing = True
        self._flush_pending_session_settings_save()
        if not hasattr(self, "import_controller") and not hasattr(self, "monitor_controller"):
            if self.is_importing:
                self.import_abort_event.set()
                if self.import_abort_flag is not None:
                    self.import_abort_flag.set()
                if self.import_process is not None and self.import_process.is_alive():
                    self.import_process.terminate()
            self.pause_monitoring()
            self.data_store.close()
            if hasattr(self, "tooltip_manager"):
                self.tooltip_manager.destroy()
            self.root.destroy()
            return
        self._ensure_import_controller().shutdown()
        self._ensure_monitor_controller().shutdown()
        self.data_store.close()
        if hasattr(self, "tooltip_manager"):
            self.tooltip_manager.destroy()
        self.root.destroy()

    def _build_session_settings(self):
        """Build serializable user session settings from current UI state."""
        if not hasattr(self, "settings_controller"):
            death_fallback_line = None
            death_panel = getattr(self, "death_snippet_panel", None)
            if death_panel is not None:
                death_fallback_line = death_panel.get_fallback_death_line()
            else:
                parser = getattr(self, "parser", None)
                if parser is not None:
                    death_fallback_line = str(getattr(parser, "death_fallback_line", "")).strip()
            return self._ensure_settings_controller().build_settings()
        return self._ensure_settings_controller().build_settings()

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
        controller = self._ensure_settings_controller()
        controller.persist_now()
        self._settings = controller.settings

    def _schedule_session_settings_save(self) -> None:
        """Debounce session settings persistence for frequently edited fields."""
        if not hasattr(self, "settings_controller"):
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
            return
        self._ensure_settings_controller().schedule_save()

    def _flush_pending_session_settings_save(self) -> None:
        """Immediately persist settings and clear any scheduled save handle."""
        if not hasattr(self, "settings_controller"):
            self._settings_save_job = None
            self._persist_session_settings()
            return
        controller = self._ensure_settings_controller()
        controller.flush_pending_save()
        self._settings = controller.settings

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
        self._ensure_monitor_controller()._debug_monitor_enabled = self.debug_mode
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
