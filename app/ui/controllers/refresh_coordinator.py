"""Batched UI refresh coordination for heavy panels."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from ...services.queue_processor import QueueDrainResult


class RefreshCoordinator:
    """Track dirty UI state and coalesce expensive refresh work."""

    def __init__(
        self,
        *,
        root: tk.Misc,
        dps_panel,
        stats_panel,
        immunity_panel,
        refresh_targets: Callable[[], None],
        on_death_snippet: Callable[[object], None],
        on_character_identified: Callable[[object], None],
        delay_ms: int = 180,
    ) -> None:
        self.root = root
        self.dps_panel = dps_panel
        self.stats_panel = stats_panel
        self.immunity_panel = immunity_panel
        self.refresh_targets = refresh_targets
        self.on_death_snippet = on_death_snippet
        self.on_character_identified = on_character_identified
        self.delay_ms = int(delay_ms)

        self._refresh_job = None
        self._dps_dirty = False
        self._targets_dirty = False
        self._immunity_dirty_targets: set[str] = set()

    def clear_dirty_state(self) -> None:
        """Reset all pending refresh state without scheduling UI work."""
        self._dps_dirty = False
        self._targets_dirty = False
        self._immunity_dirty_targets.clear()

    def cancel(self) -> None:
        """Cancel any pending batched refresh callback."""
        job = self._refresh_job
        if job is not None:
            self.root.after_cancel(job)
            self._refresh_job = None

    def schedule(self) -> None:
        """Schedule a single coalesced refresh pass."""
        if self._refresh_job is not None:
            return
        self._refresh_job = self.root.after(self.delay_ms, self.run)

    def handle_queue_result(self, result: QueueDrainResult) -> None:
        """Apply queue-drain effects and schedule expensive refresh work."""
        for death_event in result.death_events:
            self.on_death_snippet(death_event)
        for identity_event in result.character_identity_events:
            self.on_character_identified(identity_event)

        if result.dps_updated:
            self._dps_dirty = True
        if result.targets_to_refresh:
            self._targets_dirty = True

        selected_target = str(self.immunity_panel.get_selected_target() or "")
        if selected_target and (
            selected_target in result.immunity_targets
            or selected_target in result.damage_targets
        ):
            self._immunity_dirty_targets.add(selected_target)

        if self._dps_dirty or self._targets_dirty or self._immunity_dirty_targets:
            self.schedule()

    def run(self) -> None:
        """Execute one coalesced refresh pass."""
        self._refresh_job = None
        selected_target = str(self.immunity_panel.get_selected_target() or "")

        if self._targets_dirty:
            self.refresh_targets()
            self._targets_dirty = False
            selected_target = str(self.immunity_panel.get_selected_target() or "")

        if self._dps_dirty:
            self.dps_panel.refresh()
            self._dps_dirty = False

        if selected_target and selected_target in self._immunity_dirty_targets:
            self.immunity_panel.refresh_target_details(selected_target)
        self._immunity_dirty_targets.clear()
