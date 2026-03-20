"""Realtime backpressure tests for queue-drain and monitor controllers."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from time import perf_counter
from types import SimpleNamespace
import queue
import threading
from unittest.mock import Mock

import pytest

import app.ui.controllers.monitor_controller as monitor_module
from app.parser import LogParser
from app.parsed_events import AttackHitEvent, DamageDealtEvent
from app.services import QueueProcessor
from app.storage import DataStore
from app.ui.controllers.monitor_controller import MonitorController
from app.ui.controllers.queue_drain_controller import QueueDrainController
from app.ui.controllers.refresh_coordinator import RefreshCoordinator
from app.ui.main_window import WoosNwnParserApp


class _AfterRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[int, object]] = []
        self._job_id = 0

    def after(self, delay_ms: int, callback) -> str:
        self.calls.append((int(delay_ms), callback))
        self._job_id += 1
        return f"after-job-{self._job_id}"

    def after_cancel(self, _job_id: str) -> None:
        return None


class _FakeRealtimeMonitor:
    def __init__(self, events: list[object]) -> None:
        self._remaining: deque[object] = deque(events)
        self.current_log_file = SimpleNamespace(name="nwclientLog1.txt")
        self.max_lines_requests: list[int] = []
        self.produced_batch_sizes: list[int] = []

    @property
    def remaining_count(self) -> int:
        return len(self._remaining)

    def read_new_lines(
        self,
        parser,
        data_queue: queue.Queue,
        on_log_message=None,
        debug_enabled: bool = False,
        max_lines_per_poll: int = 2000,
    ) -> bool:
        del parser, debug_enabled
        self.max_lines_requests.append(max_lines_per_poll)
        produced = 0
        while produced < max_lines_per_poll and self._remaining:
            try:
                data_queue.put_nowait(self._remaining[0])
            except queue.Full:
                if on_log_message is not None:
                    on_log_message("Synthetic monitor queue saturation", "warning")
                break
            self._remaining.popleft()
            produced += 1
        self.produced_batch_sizes.append(produced)
        return bool(self._remaining)


def _make_realtime_event(index: int, now: datetime) -> DamageDealtEvent | AttackHitEvent:
    target = f"Target-{index % 5}"
    attacker = f"Woo-{index % 2}"
    if index % 2 == 0:
        return DamageDealtEvent(
            attacker=attacker,
            target=target,
            total_damage=50,
            timestamp=now,
            damage_types={"Physical": 50},
            line_number=index,
        )
    return AttackHitEvent(
        attacker=attacker,
        target=target,
        roll=15,
        bonus=10,
        total=25,
        timestamp=now,
        line_number=index,
    )


def _build_harness() -> tuple[QueueDrainController, RefreshCoordinator, MonitorController, _AfterRecorder, queue.Queue]:
    after_recorder = _AfterRecorder()
    root = Mock()
    root.after = after_recorder.after
    root.after_cancel = after_recorder.after_cancel

    parser = LogParser(parse_immunity=False)
    data_store = DataStore()
    queue_processor = QueueProcessor(data_store, parser)
    data_queue: queue.Queue = queue.Queue(maxsize=WoosNwnParserApp.DATA_QUEUE_MAXSIZE)

    dps_panel = Mock(refresh=Mock())
    stats_panel = Mock(refresh=Mock())
    immunity_panel = Mock(refresh_target_details=Mock())
    immunity_panel.target_combo.get.return_value = ""

    refresh_targets = Mock()
    refresh_coordinator = RefreshCoordinator(
        root=root,
        dps_panel=dps_panel,
        stats_panel=stats_panel,
        immunity_panel=immunity_panel,
        refresh_targets=refresh_targets,
        on_death_snippet=Mock(),
        on_character_identified=Mock(),
    )
    queue_drain = QueueDrainController(
        root=root,
        data_queue=data_queue,
        queue_processor=queue_processor,
        get_debug_enabled=lambda: False,
        log_debug=Mock(),
        refresh_coordinator=refresh_coordinator,
        queue_tick_ms_normal=WoosNwnParserApp.QUEUE_TICK_MS_NORMAL,
        queue_tick_ms_pressured=WoosNwnParserApp.QUEUE_TICK_MS_PRESSURED,
        queue_tick_ms_saturated=WoosNwnParserApp.QUEUE_TICK_MS_SATURATED,
        queue_drain_max_events_normal=WoosNwnParserApp.QUEUE_DRAIN_MAX_EVENTS_NORMAL,
        queue_drain_max_events_pressured=WoosNwnParserApp.QUEUE_DRAIN_MAX_EVENTS_PRESSURED,
        queue_drain_max_events_saturated=WoosNwnParserApp.QUEUE_DRAIN_MAX_EVENTS_SATURATED,
        queue_drain_max_time_ms_normal=WoosNwnParserApp.QUEUE_DRAIN_MAX_TIME_MS_NORMAL,
        queue_drain_max_time_ms_pressured=WoosNwnParserApp.QUEUE_DRAIN_MAX_TIME_MS_PRESSURED,
        queue_drain_max_time_ms_saturated=WoosNwnParserApp.QUEUE_DRAIN_MAX_TIME_MS_SATURATED,
        data_queue_pressured_threshold=WoosNwnParserApp.DATA_QUEUE_PRESSURED_THRESHOLD,
        data_queue_saturated_threshold=WoosNwnParserApp.DATA_QUEUE_SATURATED_THRESHOLD,
        monitor_lines_per_poll_normal=WoosNwnParserApp.MONITOR_LINES_PER_POLL_NORMAL,
        monitor_lines_per_poll_pressured=WoosNwnParserApp.MONITOR_LINES_PER_POLL_PRESSURED,
        monitor_sleep_active_normal=WoosNwnParserApp.MONITOR_SLEEP_ACTIVE_NORMAL,
        monitor_sleep_active_pressured=WoosNwnParserApp.MONITOR_SLEEP_ACTIVE_PRESSURED,
        monitor_sleep_active_saturated=WoosNwnParserApp.MONITOR_SLEEP_ACTIVE_SATURATED,
        monitor_sleep_idle_normal=WoosNwnParserApp.MONITOR_SLEEP_IDLE_NORMAL,
        monitor_sleep_idle_pressured=WoosNwnParserApp.MONITOR_SLEEP_IDLE_PRESSURED,
        monitor_sleep_idle_saturated=WoosNwnParserApp.MONITOR_SLEEP_IDLE_SATURATED,
    )
    active_files: list[str] = []
    monitor = MonitorController(
        root=root,
        parser=parser,
        data_queue=data_queue,
        debug_panel=Mock(get_debug_enabled=Mock(return_value=False)),
        dps_panel=dps_panel,
        get_log_directory=lambda: r"C:\logs",
        set_log_directory=Mock(),
        set_monitoring_switch_ui=Mock(),
        set_active_file_name=lambda file_name: active_files.append(file_name),
        log_debug=queue_drain.log_debug,
        persist_settings_now=Mock(),
        get_window_icon_path=lambda: None,
        get_queue_pressure_state=queue_drain.get_pressure_state,
        get_monitor_max_lines_per_poll=queue_drain.get_monitor_max_lines_per_poll,
        get_monitor_sleep_seconds=queue_drain.get_monitor_sleep_seconds,
    )
    monitor._captured_active_files = active_files
    return queue_drain, refresh_coordinator, monitor, after_recorder, data_queue


def test_realtime_backpressure_stress_keeps_monitor_non_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    queue_drain, refresh_coordinator, monitor, after_recorder, data_queue = _build_harness()
    total_events = WoosNwnParserApp.DATA_QUEUE_SATURATED_THRESHOLD + 1500
    now = datetime.now()
    fake_monitor = _FakeRealtimeMonitor([_make_realtime_event(index, now) for index in range(total_events)])
    monitor.directory_monitor = fake_monitor
    monitor.is_monitoring = True

    original_sleep = monitor_module.time.sleep
    recorded_sleep_durations: list[float] = []

    def fake_sleep(duration: float) -> None:
        recorded_sleep_durations.append(duration)
        original_sleep(0.001)

    monkeypatch.setattr(monitor_module.time, "sleep", fake_sleep)

    monitor_thread = threading.Thread(target=monitor.monitor_loop, name="test-backpressure-monitor", daemon=True)
    monitor.monitor_thread = monitor_thread
    monitor_thread.start()

    saturation_deadline = perf_counter() + 2.0
    observed_queue_pressure: list[str] = []
    while perf_counter() < saturation_deadline:
        pressure_state = queue_drain.get_pressure_state()
        observed_queue_pressure.append(pressure_state)
        if pressure_state == "saturated":
            break
        original_sleep(0.001)

    assert "pressured" in observed_queue_pressure or data_queue.qsize() >= WoosNwnParserApp.DATA_QUEUE_PRESSURED_THRESHOLD
    assert queue_drain.get_pressure_state() == "saturated"

    scheduled_queue_ticks: list[int] = []
    coalesced_refresh_runs = 0
    drain_deadline = perf_counter() + 5.0

    while perf_counter() < drain_deadline:
        prior_call_count = len(after_recorder.calls)
        queue_drain.tick()
        new_calls = after_recorder.calls[prior_call_count:]
        scheduled_queue_ticks.extend(
            delay_ms
            for delay_ms, callback in new_calls
            if getattr(callback, "__name__", "") == "tick"
        )
        if refresh_coordinator._refresh_job is not None:
            coalesced_refresh_runs += 1
            refresh_coordinator.run()
        if fake_monitor.remaining_count == 0 and data_queue.empty():
            break
        original_sleep(0.001)

    monitor.monitor_stop_event.set()
    monitor_thread.join(timeout=2.0)
    monitor.drain_monitor_logs()

    assert monitor_thread.is_alive() is False
    assert fake_monitor.remaining_count == 0
    assert data_queue.qsize() == 0
    assert queue_drain.get_pressure_state() == "normal"
    assert WoosNwnParserApp.MONITOR_LINES_PER_POLL_PRESSURED in fake_monitor.max_lines_requests
    assert WoosNwnParserApp.MONITOR_SLEEP_ACTIVE_SATURATED in recorded_sleep_durations
    assert WoosNwnParserApp.QUEUE_TICK_MS_PRESSURED in scheduled_queue_ticks
    assert coalesced_refresh_runs > 0
    assert monitor.dps_panel.refresh.call_count == coalesced_refresh_runs
    assert refresh_coordinator.refresh_targets.call_count == coalesced_refresh_runs


def test_monitor_loop_uses_post_read_pressure_for_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    queue_drain, _refresh_coordinator, monitor, _after_recorder, data_queue = _build_harness()
    now = datetime.now()
    for _ in range(WoosNwnParserApp.DATA_QUEUE_PRESSURED_THRESHOLD - 500):
        data_queue.put(
            DamageDealtEvent(
                attacker="seed",
                target="seed-target",
                total_damage=1,
                timestamp=now,
                damage_types={"Physical": 1},
                line_number=-1,
            )
        )
    fake_monitor = _FakeRealtimeMonitor(
        [_make_realtime_event(index, now) for index in range(WoosNwnParserApp.MONITOR_LINES_PER_POLL_NORMAL)]
    )
    monitor.directory_monitor = fake_monitor
    monitor.is_monitoring = True

    recorded_sleep_durations: list[float] = []

    def fake_sleep(duration: float) -> None:
        recorded_sleep_durations.append(duration)
        monitor.monitor_stop_event.set()

    monkeypatch.setattr(monitor_module.time, "sleep", fake_sleep)

    monitor.monitor_loop()

    assert fake_monitor.max_lines_requests[0] == WoosNwnParserApp.MONITOR_LINES_PER_POLL_NORMAL
    assert recorded_sleep_durations == [WoosNwnParserApp.MONITOR_SLEEP_ACTIVE_SATURATED]
