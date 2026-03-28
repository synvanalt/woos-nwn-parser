"""Settings load/save orchestration for the Tk app."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from ...settings import AppSettings, load_app_settings, save_app_settings


class SessionSettingsController:
    """Manage session settings persistence and debounced saves."""

    def __init__(
        self,
        *,
        root: tk.Misc | None,
        parser,
        get_log_directory: Callable[[], str],
        get_death_fallback_line: Callable[[], str],
        get_first_timestamp_mode: Callable[[], str | None],
        save_delay_ms: int = 400,
        load_settings: Callable[[], AppSettings] = load_app_settings,
        save_settings: Callable[[AppSettings], None] = save_app_settings,
    ) -> None:
        self.root = root
        self.parser = parser
        self.get_log_directory = get_log_directory
        self.get_death_fallback_line = get_death_fallback_line
        self.get_first_timestamp_mode = get_first_timestamp_mode
        self.save_delay_ms = int(save_delay_ms)
        self._load_settings = load_settings
        self._save_settings = save_settings

        self._settings = AppSettings()
        self._settings_save_job = None

    def load_initial_settings(self) -> AppSettings:
        """Load and remember persisted settings."""
        self._settings = self._load_settings()
        return self._settings

    def build_settings(self) -> AppSettings:
        """Build serializable session settings from live UI/service state."""
        return AppSettings(
            log_directory=(self.get_log_directory() or "").strip() or None,
            death_fallback_line=(self.get_death_fallback_line() or "").strip() or None,
            parse_immunity=bool(self.parser.parse_immunity),
            first_timestamp_mode=self.get_first_timestamp_mode(),
        )

    def persist_now(self) -> None:
        """Persist settings immediately."""
        settings = self.build_settings()
        self._settings = settings
        try:
            self._save_settings(settings)
        except OSError:
            return

    def schedule_save(self) -> None:
        """Debounce settings persistence on the Tk event loop."""
        if self.root is None:
            self.persist_now()
            return
        if self._settings_save_job is not None:
            try:
                self.root.after_cancel(self._settings_save_job)
            except tk.TclError:
                pass
        self._settings_save_job = self.root.after(self.save_delay_ms, self.flush_pending_save)

    def flush_pending_save(self) -> None:
        """Persist settings and clear the pending timer handle."""
        self._settings_save_job = None
        self.persist_now()
