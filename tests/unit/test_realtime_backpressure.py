"""Realtime backpressure stress tests for monitor/UI coordination."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from time import perf_counter
from types import SimpleNamespace
import queue
import threading
from unittest.mock import Mock

import pytest

import app.ui.main_window as main_window_module
from app.parser import LogParser
from app.services import QueueProcessor
from app.storage import DataStore
from app.ui.main_window import WoosNwnParserApp


class _AfterRecorder:
    """Capture scheduled callbacks without running a Tk event loop."""

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
    """Feed parsed events into the bounded realtime queue like the monitor thread."""

    def __init__(self, events: list[dict]) -> None:
        self._remaining: deque[dict] = deque(events)
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


def _make_realtime_event(index: int, now: datetime) -> dict:
    """Generate mixed high-volume combat events for queue pressure tests."""
    target = f"Target-{index % 5}"
    attacker = f"Woo-{index % 2}"
    if index % 2 == 0:
        return {
            "type": "damage_dealt",
            "attacker": attacker,
            "target": target,
            "total_damage": 50,
            "timestamp": now,
            "damage_types": {"Physical": 50},
        }
    return {
        "type": "attack_hit",
        "attacker": attacker,
        "target": target,
        "roll": 15,
        "bonus": 10,
        "total": 25,
        "timestamp": now,
    }


def _build_app_shell() -> tuple[WoosNwnParserApp, _AfterRecorder]:
    """Create a minimal app harness with real queue-processing services."""
    app = WoosNwnParserApp.__new__(WoosNwnParserApp)
    after_recorder = _AfterRecorder()

    app.root = Mock()
    app.root.after = after_recorder.after
    app.root.after_cancel = after_recorder.after_cancel
    app.root.destroy = Mock()

    app.parser = LogParser(parse_immunity=False)
    app.data_store = DataStore()
    app.queue_processor = QueueProcessor(app.data_store, app.parser)
    app.data_queue = queue.Queue(maxsize=WoosNwnParserApp.DATA_QUEUE_MAXSIZE)

    app.log_debug = Mock()
    app.debug_panel = Mock()
    app.debug_panel.get_debug_enabled.return_value = False

    app.dps_panel = Mock()
    app.dps_panel.refresh = Mock()
    app.immunity_panel = Mock()
    app.immunity_panel.target_combo.get.return_value = ""
    app.immunity_panel.refresh_target_details = Mock()
    app.refresh_targets = Mock()

    app._dps_dirty = False
    app._targets_dirty = False
    app._immunity_dirty_targets = set()
    app._queue_tick_ms = WoosNwnParserApp.QUEUE_TICK_MS_NORMAL
    app._queue_pressure_state = "normal"
    app._refresh_job = None

    app.is_monitoring = True
    app.monitor_stop_event = threading.Event()
    app.monitor_thread = None
    app._monitor_active_file_name = "-"
    app._monitor_log_queue = queue.SimpleQueue()
    app._debug_monitor_enabled = False
    app.polling_job = None
    app.dps_refresh_job = None

    return app, after_recorder


def test_realtime_backpressure_stress_keeps_monitor_non_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Producer-faster-than-consumer bursts should saturate, recover, and stay coalesced."""
    app, after_recorder = _build_app_shell()
    total_events = WoosNwnParserApp.DATA_QUEUE_SATURATED_THRESHOLD + 1500
    now = datetime.now()
    fake_monitor = _FakeRealtimeMonitor(
        [_make_realtime_event(index, now) for index in range(total_events)]
    )
    app.directory_monitor = fake_monitor

    original_sleep = main_window_module.time.sleep
    recorded_sleep_durations: list[float] = []

    def fake_sleep(duration: float) -> None:
        recorded_sleep_durations.append(duration)
        original_sleep(0.001)

    monkeypatch.setattr(main_window_module.time, "sleep", fake_sleep)

    monitor_thread = threading.Thread(
        target=app._monitor_loop,
        name="test-backpressure-monitor",
        daemon=True,
    )
    app.monitor_thread = monitor_thread
    monitor_thread.start()

    saturation_deadline = perf_counter() + 2.0
    observed_queue_pressure: list[str] = []
    while perf_counter() < saturation_deadline:
        pressure_state = app._get_queue_pressure_state()
        observed_queue_pressure.append(pressure_state)
        if pressure_state == "saturated":
            break
        original_sleep(0.001)

    assert "pressured" in observed_queue_pressure or app.data_queue.qsize() >= app.DATA_QUEUE_PRESSURED_THRESHOLD
    assert app._get_queue_pressure_state() == "saturated"

    scheduled_queue_ticks: list[int] = []
    coalesced_refresh_runs = 0
    drain_deadline = perf_counter() + 5.0

    while perf_counter() < drain_deadline:
        prior_call_count = len(after_recorder.calls)
        app.process_queue()
        new_calls = after_recorder.calls[prior_call_count:]
        scheduled_queue_ticks.extend(
            delay_ms
            for delay_ms, callback in new_calls
            if getattr(callback, "__name__", "") == "process_queue"
        )

        if app._refresh_job is not None:
            coalesced_refresh_runs += 1
            app._run_coalesced_refresh()

        if fake_monitor.remaining_count == 0 and app.data_queue.empty():
            break

        original_sleep(0.001)

    app.monitor_stop_event.set()
    monitor_thread.join(timeout=2.0)
    app._drain_monitor_logs()

    assert monitor_thread.is_alive() is False
    assert fake_monitor.remaining_count == 0
    assert app.data_queue.qsize() == 0
    assert app._get_queue_pressure_state() == "normal"

    assert WoosNwnParserApp.MONITOR_LINES_PER_POLL_PRESSURED in fake_monitor.max_lines_requests
    assert WoosNwnParserApp.MONITOR_SLEEP_ACTIVE_SATURATED in recorded_sleep_durations
    assert WoosNwnParserApp.QUEUE_TICK_MS_PRESSURED in scheduled_queue_ticks

    assert coalesced_refresh_runs > 0
    assert app.dps_panel.refresh.call_count == coalesced_refresh_runs
    assert app.refresh_targets.call_count == coalesced_refresh_runs
    assert app.dps_panel.refresh.call_count < total_events
    assert app.refresh_targets.call_count < total_events

    logged_messages = [call.args for call in app.log_debug.call_args_list]
    assert not any("I/O Error" in str(message) for message, *_ in logged_messages)
    assert not any("queue.Full" in str(message) for message, *_ in logged_messages)
