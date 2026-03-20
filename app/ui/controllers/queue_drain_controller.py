"""Queue draining and backpressure orchestration for the Tk UI."""

from __future__ import annotations

import tkinter as tk


class QueueDrainController:
    """Own queue-drain cadence and backpressure policy."""

    def __init__(
        self,
        *,
        root: tk.Misc,
        data_queue,
        queue_processor,
        get_debug_enabled,
        log_debug,
        refresh_coordinator,
        queue_tick_ms_normal: int,
        queue_tick_ms_pressured: int,
        queue_tick_ms_saturated: int,
        queue_drain_max_events_normal: int,
        queue_drain_max_events_pressured: int,
        queue_drain_max_events_saturated: int,
        queue_drain_max_time_ms_normal: float,
        queue_drain_max_time_ms_pressured: float,
        queue_drain_max_time_ms_saturated: float,
        data_queue_pressured_threshold: int,
        data_queue_saturated_threshold: int,
        monitor_lines_per_poll_normal: int,
        monitor_lines_per_poll_pressured: int,
        monitor_sleep_active_normal: float,
        monitor_sleep_active_pressured: float,
        monitor_sleep_active_saturated: float,
        monitor_sleep_idle_normal: float,
        monitor_sleep_idle_pressured: float,
        monitor_sleep_idle_saturated: float,
    ) -> None:
        self.root = root
        self.data_queue = data_queue
        self.queue_processor = queue_processor
        self.get_debug_enabled = get_debug_enabled
        self.log_debug = log_debug
        self.refresh_coordinator = refresh_coordinator

        self.queue_tick_ms_normal = int(queue_tick_ms_normal)
        self.queue_tick_ms_pressured = int(queue_tick_ms_pressured)
        self.queue_tick_ms_saturated = int(queue_tick_ms_saturated)
        self.queue_drain_max_events_normal = int(queue_drain_max_events_normal)
        self.queue_drain_max_events_pressured = int(queue_drain_max_events_pressured)
        self.queue_drain_max_events_saturated = int(queue_drain_max_events_saturated)
        self.queue_drain_max_time_ms_normal = float(queue_drain_max_time_ms_normal)
        self.queue_drain_max_time_ms_pressured = float(queue_drain_max_time_ms_pressured)
        self.queue_drain_max_time_ms_saturated = float(queue_drain_max_time_ms_saturated)
        self.data_queue_pressured_threshold = int(data_queue_pressured_threshold)
        self.data_queue_saturated_threshold = int(data_queue_saturated_threshold)
        self.monitor_lines_per_poll_normal = int(monitor_lines_per_poll_normal)
        self.monitor_lines_per_poll_pressured = int(monitor_lines_per_poll_pressured)
        self.monitor_sleep_active_normal = float(monitor_sleep_active_normal)
        self.monitor_sleep_active_pressured = float(monitor_sleep_active_pressured)
        self.monitor_sleep_active_saturated = float(monitor_sleep_active_saturated)
        self.monitor_sleep_idle_normal = float(monitor_sleep_idle_normal)
        self.monitor_sleep_idle_pressured = float(monitor_sleep_idle_pressured)
        self.monitor_sleep_idle_saturated = float(monitor_sleep_idle_saturated)

        self._queue_tick_ms = self.queue_tick_ms_normal
        self._queue_pressure_state = "normal"

    @property
    def pressure_state(self) -> str:
        return self._queue_pressure_state

    def start(self) -> None:
        self.tick()

    def tick(self) -> None:
        starting_pressure_state = self.get_pressure_state()
        max_events, max_time_ms = self._get_queue_drain_limits(starting_pressure_state)
        result = self.queue_processor.process_queue(
            self.data_queue,
            on_log_message=self.log_debug,
            debug_enabled=bool(self.get_debug_enabled()),
            max_events=max_events,
            max_time_ms=max_time_ms,
        )
        pressure_state = getattr(result, "pressure_state", "normal")
        if pressure_state not in {"normal", "pressured", "saturated"}:
            pressure_state = "normal"
        self._queue_pressure_state = pressure_state
        self.refresh_coordinator.handle_queue_result(result)
        self.root.after(self._get_next_queue_tick_ms(pressure_state), self.tick)

    def get_pressure_state(self) -> str:
        queue_depth = self._get_queue_depth_hint()
        if queue_depth >= self.data_queue_saturated_threshold:
            return "saturated"
        if queue_depth >= self.data_queue_pressured_threshold:
            return "pressured"
        return "normal"

    def get_monitor_max_lines_per_poll(self, pressure_state: str) -> int:
        if pressure_state == "pressured":
            return self.monitor_lines_per_poll_pressured
        return self.monitor_lines_per_poll_normal

    def get_monitor_sleep_seconds(self, pressure_state: str, has_more_pending: bool) -> float:
        if pressure_state == "saturated":
            return self.monitor_sleep_active_saturated
        if has_more_pending:
            if pressure_state == "pressured":
                return self.monitor_sleep_active_pressured
            return self.monitor_sleep_active_normal
        if pressure_state == "pressured":
            return self.monitor_sleep_idle_pressured
        return self.monitor_sleep_idle_normal

    def _get_queue_depth_hint(self) -> int:
        try:
            size = int(self.data_queue.qsize())
        except (AttributeError, NotImplementedError):
            return 0
        return max(size, 0)

    def _get_queue_drain_limits(self, pressure_state: str) -> tuple[int, float]:
        if pressure_state == "saturated":
            return self.queue_drain_max_events_saturated, self.queue_drain_max_time_ms_saturated
        if pressure_state == "pressured":
            return self.queue_drain_max_events_pressured, self.queue_drain_max_time_ms_pressured
        return self.queue_drain_max_events_normal, self.queue_drain_max_time_ms_normal

    def _get_next_queue_tick_ms(self, pressure_state: str) -> int:
        if pressure_state == "saturated":
            return self.queue_tick_ms_saturated
        if pressure_state == "pressured":
            return self.queue_tick_ms_pressured
        return self._queue_tick_ms
