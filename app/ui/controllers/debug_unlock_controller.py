"""Hidden debug-tab unlock gesture handling."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

import tkinter as tk

from ..runtime_config import DebugUnlockPolicy


class DebugUnlockController:
    """Track DPS-tab click cadence and reveal the debug tab when unlocked."""

    def __init__(
        self,
        *,
        notebook,
        policy: DebugUnlockPolicy,
        is_debug_tab_visible: Callable[[], bool],
        on_unlock: Callable[[], None],
    ) -> None:
        self.notebook = notebook
        self.policy = policy
        self.is_debug_tab_visible = is_debug_tab_visible
        self.on_unlock = on_unlock
        self._dps_tab_click_times: deque[float] = deque()

    @property
    def click_times(self) -> deque[float]:
        return self._dps_tab_click_times

    def handle_notebook_click(self, event: tk.Event) -> None:
        """Inspect notebook tab clicks and unlock debug when the gesture matches."""
        if self.is_debug_tab_visible() or self.notebook is None:
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
        if clicked_tab_text != self.policy.dps_tab_text:
            self._dps_tab_click_times.clear()
            return
        self.record_click_and_maybe_unlock()

    def record_click_and_maybe_unlock(self) -> None:
        """Track one DPS-tab click and unlock when enough clicks fit in the window."""
        now = time.monotonic()
        self._dps_tab_click_times.append(now)
        window_start = now - self.policy.window_seconds
        while self._dps_tab_click_times and self._dps_tab_click_times[0] < window_start:
            self._dps_tab_click_times.popleft()
        if len(self._dps_tab_click_times) >= self.policy.click_target:
            self.on_unlock()
            self._dps_tab_click_times.clear()
