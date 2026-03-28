"""Main application window for Woo's NWN Parser."""

from __future__ import annotations

import queue
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import font, ttk

from ..parsed_events import DeathCharacterIdentifiedEvent, DeathSnippetEvent
from ..parser import ParserSession
from ..services import QueueProcessor
from ..services.queries import DpsQueryService, ImmunityQueryService, TargetSummaryQueryService
from ..settings import load_app_settings, save_app_settings
from ..storage import DataStore
from .controllers import (
    DebugUnlockController,
    ImportController,
    MonitorController,
    QueueDrainController,
    RefreshCoordinator,
    SessionSettingsController,
)
from .formatters import get_default_log_directory
from .runtime_config import DEFAULT_APP_RUNTIME_CONFIG
from .tooltips import TooltipManager
from .widgets import DebugConsolePanel, DPSPanel, DeathSnippetPanel, ImmunityPanel, TargetStatsPanel


class WoosNwnParserApp:
    """Main Tk application window."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Woo's NWN Parser")
        self.root.geometry("730x550")
        self.runtime_config = DEFAULT_APP_RUNTIME_CONFIG

        self.log_directory = ""
        self.window_icon_path: Optional[str] = None
        self.notebook: ttk.Notebook | None = None
        self._is_closing = False

        self.parser = ParserSession(parse_immunity=True)
        self.data_store = DataStore()
        self.queue_processor = QueueProcessor(self.data_store, self.parser)
        self.dps_query_service = DpsQueryService(self.data_store)
        self.target_summary_query_service = TargetSummaryQueryService(self.data_store)
        self.immunity_query_service = ImmunityQueryService(self.data_store)
        self.data_queue: queue.Queue = queue.Queue(
            maxsize=self.runtime_config.queue.data_queue_maxsize
        )

        self.settings_controller = SessionSettingsController(
            root=self.root,
            parser=self.parser,
            get_log_directory=lambda: self.log_directory,
            get_death_fallback_line=self._get_death_fallback_line_for_settings,
            get_first_timestamp_mode=self._get_current_first_timestamp_mode,
            load_settings=load_app_settings,
            save_settings=save_app_settings,
        )
        initial_settings = self.settings_controller.load_initial_settings()

        parse_immunity_enabled = initial_settings.parse_immunity
        self.parser.parse_immunity = True if parse_immunity_enabled is None else bool(parse_immunity_enabled)

        persisted_mode = initial_settings.first_timestamp_mode
        if persisted_mode is not None:
            self.dps_query_service.set_time_tracking_mode(persisted_mode)

        configured_log_directory = (initial_settings.log_directory or "").strip()
        self.log_directory = configured_log_directory or get_default_log_directory()
        configured_fallback_line = (initial_settings.death_fallback_line or "").strip()
        self._initial_death_fallback_line = (
            configured_fallback_line or ParserSession.DEFAULT_DEATH_FALLBACK_LINE
        )

        self._debug_tab_visible = False

        self.theme_font = font.nametofont("SunValleyBodyFont")
        self.tooltip_manager = TooltipManager(self.root)

        self.setup_ui()
        self.refresh_coordinator = RefreshCoordinator(
            root=self.root,
            dps_panel=self.dps_panel,
            stats_panel=self.stats_panel,
            immunity_panel=self.immunity_panel,
            refresh_targets=self.refresh_targets,
            on_death_snippet=self._on_death_snippet,
            on_character_identified=self._on_death_character_identified,
        )
        self.queue_drain_controller = QueueDrainController(
            root=self.root,
            data_queue=self.data_queue,
            queue_processor=self.queue_processor,
            get_debug_enabled=self.debug_panel.get_debug_enabled,
            log_debug=self.log_debug,
            refresh_coordinator=self.refresh_coordinator,
            queue_tick_ms_normal=self.runtime_config.queue.queue_tick_ms_normal,
            queue_tick_ms_pressured=self.runtime_config.queue.queue_tick_ms_pressured,
            queue_tick_ms_saturated=self.runtime_config.queue.queue_tick_ms_saturated,
            queue_drain_max_events_normal=self.runtime_config.queue.queue_drain_max_events_normal,
            queue_drain_max_events_pressured=self.runtime_config.queue.queue_drain_max_events_pressured,
            queue_drain_max_events_saturated=self.runtime_config.queue.queue_drain_max_events_saturated,
            queue_drain_max_time_ms_normal=self.runtime_config.queue.queue_drain_max_time_ms_normal,
            queue_drain_max_time_ms_pressured=self.runtime_config.queue.queue_drain_max_time_ms_pressured,
            queue_drain_max_time_ms_saturated=self.runtime_config.queue.queue_drain_max_time_ms_saturated,
            data_queue_pressured_threshold=self.runtime_config.queue.data_queue_pressured_threshold,
            data_queue_saturated_threshold=self.runtime_config.queue.data_queue_saturated_threshold,
            monitor_lines_per_poll_normal=self.runtime_config.monitor.lines_per_poll_normal,
            monitor_lines_per_poll_pressured=self.runtime_config.monitor.lines_per_poll_pressured,
            monitor_sleep_active_normal=self.runtime_config.monitor.sleep_active_normal,
            monitor_sleep_active_pressured=self.runtime_config.monitor.sleep_active_pressured,
            monitor_sleep_active_saturated=self.runtime_config.monitor.sleep_active_saturated,
            monitor_sleep_idle_normal=self.runtime_config.monitor.sleep_idle_normal,
            monitor_sleep_idle_pressured=self.runtime_config.monitor.sleep_idle_pressured,
            monitor_sleep_idle_saturated=self.runtime_config.monitor.sleep_idle_saturated,
        )
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
            get_queue_pressure_state=self.queue_drain_controller.get_pressure_state,
            get_monitor_max_lines_per_poll=self.queue_drain_controller.get_monitor_max_lines_per_poll,
            get_monitor_sleep_seconds=self.queue_drain_controller.get_monitor_sleep_seconds,
        )
        self.monitor_controller.configure_switch_style()
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
            import_apply_frame_budget_ms=self.runtime_config.import_.apply_frame_budget_ms,
            import_apply_mutation_batch_size=self.runtime_config.import_.apply_mutation_batch_size,
        )
        self.debug_unlock_controller = DebugUnlockController(
            notebook=self.notebook,
            policy=self.runtime_config.debug_unlock,
            is_debug_tab_visible=lambda: self._debug_tab_visible,
            on_unlock=self._show_debug_tab,
        )

        self.process_queue()

        if self.log_directory and Path(self.log_directory).is_dir():
            self.root.after(100, self.start_monitoring)
        else:
            self._set_monitoring_switch_ui(False)

    def setup_ui(self) -> None:
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(fill="x")

        file_frame = ttk.Frame(control_frame)
        file_frame.pack(fill="x", pady=(0, 10))

        self.log_directory_label = ttk.Label(file_frame, text="Log Directory:")
        self.log_directory_label.pack(side="left", padx=5)
        self.dir_text = tk.StringVar(value="No directory selected")
        self.dir_label = ttk.Entry(
            file_frame,
            state="readonly",
            textvariable=self.dir_text,
            foreground="gray",
            width=40,
        )
        self.dir_label.pack(side="left", fill="x", expand=True, padx=(2, 2))

        self.active_file_name_label = ttk.Label(file_frame, text="File:")
        self.active_file_name_label.pack(side="left", padx=(10, 0))
        self.active_file_text = tk.StringVar(value="N/A")
        self.active_file_label = ttk.Entry(
            file_frame,
            state="readonly",
            textvariable=self.active_file_text,
            foreground="gray",
            width=13,
        )
        self.active_file_label.pack(side="left", padx=5)

        self.browse_button = ttk.Button(file_frame, text="Browse...", command=self.browse_directory)
        self.browse_button.pack(side="left", padx=5)

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

        self.load_parse_button = ttk.Button(
            buttons_frame,
            text="Load & Parse Logs",
            command=self.load_and_parse_selected_files,
        )
        self.load_parse_button.pack(side="right", padx=5)

        if self.log_directory:
            self.dir_text.set(value=self.log_directory.replace("/", "\\"))

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.dps_panel = DPSPanel(
            self.notebook,
            self.data_store,
            self.dps_query_service,
            tooltip_manager=self.tooltip_manager,
        )
        self._restore_persisted_dps_panel_state()
        self.notebook.add(self.dps_panel, text=self.runtime_config.debug_unlock.dps_tab_text)
        self.dps_panel.time_tracking_combo.bind("<<ComboboxSelected>>", self._on_time_tracking_mode_changed)
        self.dps_panel.target_filter_combo.bind("<<ComboboxSelected>>", self._on_target_filter_changed)

        self.stats_panel = TargetStatsPanel(
            self.notebook,
            self.data_store,
            self.target_summary_query_service,
            tooltip_manager=self.tooltip_manager,
        )
        self.notebook.add(self.stats_panel, text="Target Stats")

        self.immunity_panel = ImmunityPanel(
            self.notebook,
            self.data_store,
            self.parser,
            self.immunity_query_service,
            tooltip_manager=self.tooltip_manager,
            on_parse_immunity_changed=self._on_parse_immunity_changed,
        )
        self.notebook.add(self.immunity_panel, text="Target Immunities")
        self.immunity_panel.target_combo.bind("<<ComboboxSelected>>", self.on_target_selected)

        self.death_snippet_panel = DeathSnippetPanel(self.notebook, tooltip_manager=self.tooltip_manager)
        self.death_snippet_panel.set_fallback_death_line(self._initial_death_fallback_line)
        self.notebook.add(self.death_snippet_panel, text="Death Snippets")
        self.death_snippet_panel.configure_identity_callbacks(
            on_character_name_changed=self._on_death_character_name_changed,
            on_fallback_line_changed=self._on_death_fallback_line_changed,
        )
        self.parser.set_death_character_name(self.death_snippet_panel.get_character_name())
        self.parser.set_death_fallback_line(self.death_snippet_panel.get_fallback_death_line())

        self.debug_panel = DebugConsolePanel(self.notebook, tooltip_manager=self.tooltip_manager)
        self.debug_panel.debug_mode_var.trace("w", self._on_debug_toggle)
        self.notebook.bind("<Button-1>", self._on_notebook_click, add=True)
        self._register_tooltips()

    def _register_tooltips(self) -> None:
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
        self.tooltip_manager.register(self.monitoring_switch, "Turn live log monitoring on or off")
        self.tooltip_manager.register(self.clear_button, "Clear all parsed data from this session")
        self.tooltip_manager.register(
            self.load_parse_button,
            "Select one or more existing log files and parse them on demand",
        )

    def _set_log_directory(self, directory: str) -> None:
        self.log_directory = directory
        self.dir_text.set(value=directory.replace("/", "\\"))

    def _set_active_file_name(self, file_name: str) -> None:
        self.active_file_text.set(value=file_name or "N/A")

    def _set_monitoring_switch_ui(self, is_on: bool) -> None:
        self.monitoring_var.set(is_on)
        self.monitoring_text.set("Monitoring" if is_on else "Paused")

    def _set_import_ui_busy(self, is_busy: bool) -> None:
        state = tk.DISABLED if is_busy else tk.NORMAL
        self.monitoring_switch.config(state=state)
        self.browse_button.config(state=state)
        self.load_parse_button.config(state=state)
        self.clear_button.config(state=state)

    def _center_window_on_parent(self, window: tk.Toplevel, width: int, height: int) -> None:
        self.root.update_idletasks()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        x = max(0, root_x + (root_w - width) // 2)
        y = max(0, root_y + (root_h - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _apply_modal_icon(self, window: tk.Toplevel) -> None:
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
        self.window_icon_path = icon_path

    def browse_directory(self) -> None:
        self.monitor_controller.browse_for_directory()

    def process_queue(self) -> None:
        self.queue_drain_controller.start()

    def load_and_parse_selected_files(self) -> None:
        self.import_controller.start_from_dialog(is_monitoring=self.monitor_controller.is_monitoring)

    def abort_load_parse(self) -> None:
        self.import_controller.abort()

    def start_monitoring(self) -> None:
        self.monitor_controller.start()

    def pause_monitoring(self) -> None:
        self.monitor_controller.pause()
        self.refresh_coordinator.cancel()

    def clear_data(self) -> None:
        self.refresh_coordinator.cancel()
        self.refresh_coordinator.clear_dirty_state()

        self.data_store.clear_all_data()

        self.immunity_panel.tree.delete(*self.immunity_panel.tree.get_children())
        self.dps_panel.tree.delete(*self.dps_panel.tree.get_children())
        self.stats_panel.tree.delete(*self.stats_panel.tree.get_children())
        self.death_snippet_panel.clear()
        self.immunity_panel.target_combo.set("")

        self.immunity_panel.clear_cache()
        self.dps_panel.clear_cache()
        self.stats_panel.clear_cache()
        self.dps_query_service.set_global_start_time(None)
        self.dps_panel.reset_target_filter()
        self.refresh_targets()

    def refresh_targets(self) -> None:
        targets = self.data_store.get_all_targets()
        self.update_target_selector_list(targets)
        self.update_target_filter_list(targets)
        self.stats_panel.refresh()
        if not self.immunity_panel.target_combo.get() and targets:
            self.immunity_panel.target_combo.current(0)
            self.on_target_selected(None)

    def update_target_selector_list(self, targets: list[str] | None = None) -> None:
        if targets is None:
            targets = self.data_store.get_all_targets()
        self.immunity_panel.update_target_list(targets)

    def update_target_filter_list(self, targets: list[str] | None = None) -> None:
        if targets is None:
            targets = self.data_store.get_all_targets()
        self.dps_panel.update_target_filter_options(targets)

    def on_target_selected(self, event) -> None:
        if event:
            event.widget.selection_clear()
        target = self.immunity_panel.target_combo.get()
        if target:
            self.immunity_panel.refresh_target_details(target)

    def _on_time_tracking_mode_changed(self, event: tk.Event) -> None:
        event.widget.selection_clear()
        new_mode_display = self.dps_panel.time_tracking_var.get()
        new_mode = new_mode_display.lower().replace(" ", "_")
        if new_mode == self.dps_query_service.time_tracking_mode:
            return
        self.dps_query_service.set_time_tracking_mode(new_mode)
        self._schedule_session_settings_save()
        self.log_debug(f"First timestamp mode changed to: {new_mode_display}")
        self.dps_panel.refresh()

    def _on_target_filter_changed(self, event: tk.Event) -> None:
        event.widget.selection_clear()
        self.log_debug(f"Target filter changed to: {self.dps_panel.target_filter_var.get()}")
        self.dps_panel.refresh()

    def _on_death_snippet(self, event: DeathSnippetEvent) -> None:
        self.death_snippet_panel.add_death_event(event)

    def _on_death_character_identified(self, event: DeathCharacterIdentifiedEvent) -> None:
        character_name = event.character_name.strip()
        if not character_name:
            return
        if self.death_snippet_panel.get_character_name():
            return
        self.death_snippet_panel.set_character_name(character_name)

    def _on_death_character_name_changed(self, name: str) -> None:
        self.parser.set_death_character_name(name)

    def _on_death_fallback_line_changed(self, line: str) -> None:
        self.parser.set_death_fallback_line(line)
        self._schedule_session_settings_save()

    def _on_parse_immunity_changed(self, enabled: bool) -> None:
        self.parser.parse_immunity = bool(enabled)
        self._schedule_session_settings_save()

    def _get_death_fallback_line_for_settings(self) -> str:
        return self.death_snippet_panel.get_fallback_death_line()

    def _restore_persisted_dps_panel_state(self) -> None:
        mode_display_by_value = {
            "per_character": "Per Character",
            "global": "Global",
        }
        current_mode = self.dps_query_service.time_tracking_mode
        self.dps_panel.time_tracking_var.set(mode_display_by_value.get(current_mode, "Per Character"))

    def _get_current_first_timestamp_mode(self) -> str | None:
        mode = self.dps_panel.get_time_tracking_mode()
        if mode in {"per_character", "global"}:
            return mode
        return None

    def _persist_session_settings(self) -> None:
        self.settings_controller.persist_now()

    def _schedule_session_settings_save(self) -> None:
        self.settings_controller.schedule_save()

    def _flush_pending_session_settings_save(self) -> None:
        self.settings_controller.flush_pending_save()

    def log_debug(self, message: str, msg_type: str = "debug") -> None:
        self.debug_panel.log(message, msg_type)

    def _on_debug_toggle(self, *args) -> None:
        del args
        debug_mode = bool(self.debug_panel.debug_mode_var.get())
        self.monitor_controller.set_debug_enabled(debug_mode)
        self.log_debug(f"Debug output {'enabled' if debug_mode else 'disabled'}")

    def _on_monitoring_switch_toggle(self) -> None:
        if self.monitoring_var.get():
            self.start_monitoring()
        else:
            self.pause_monitoring()

    def on_closing(self) -> None:
        if self._is_closing:
            return
        self._is_closing = True
        self._flush_pending_session_settings_save()
        self.import_controller.shutdown()
        self.monitor_controller.shutdown()
        self.data_store.close()
        self.tooltip_manager.destroy()
        self.root.destroy()

    def _on_notebook_click(self, event: tk.Event) -> None:
        self.debug_unlock_controller.handle_notebook_click(event)

    def _show_debug_tab(self) -> None:
        if self._debug_tab_visible or self.notebook is None:
            return
        self.notebook.add(self.debug_panel, text=self.runtime_config.debug_unlock.debug_tab_text)
        self._debug_tab_visible = True
