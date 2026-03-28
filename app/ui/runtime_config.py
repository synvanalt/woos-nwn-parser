"""Typed runtime policy for the Tk app shell and UI controllers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueRuntimePolicy:
    """Queue-drain cadence and threshold tuning."""

    data_queue_maxsize: int
    data_queue_pressured_threshold: int
    data_queue_saturated_threshold: int
    queue_tick_ms_normal: int
    queue_tick_ms_pressured: int
    queue_tick_ms_saturated: int
    queue_drain_max_events_normal: int
    queue_drain_max_events_pressured: int
    queue_drain_max_events_saturated: int
    queue_drain_max_time_ms_normal: float
    queue_drain_max_time_ms_pressured: float
    queue_drain_max_time_ms_saturated: float


@dataclass(frozen=True)
class MonitorRuntimePolicy:
    """Pressure-aware monitor polling policy."""

    lines_per_poll_normal: int
    lines_per_poll_pressured: int
    sleep_active_normal: float
    sleep_active_pressured: float
    sleep_active_saturated: float
    sleep_idle_normal: float
    sleep_idle_pressured: float
    sleep_idle_saturated: float


@dataclass(frozen=True)
class ImportRuntimePolicy:
    """Incremental import payload application policy."""

    apply_frame_budget_ms: float
    apply_mutation_batch_size: int


@dataclass(frozen=True)
class DebugUnlockPolicy:
    """Hidden debug tab unlock gesture policy."""

    click_target: int
    window_seconds: float
    dps_tab_text: str = "Damage Per Second"
    debug_tab_text: str = "Debug Console"


@dataclass(frozen=True)
class AppRuntimeConfig:
    """Top-level runtime policy bundle."""

    queue: QueueRuntimePolicy
    monitor: MonitorRuntimePolicy
    import_: ImportRuntimePolicy
    debug_unlock: DebugUnlockPolicy


DEFAULT_APP_RUNTIME_CONFIG = AppRuntimeConfig(
    queue=QueueRuntimePolicy(
        data_queue_maxsize=4000,
        data_queue_pressured_threshold=2000,
        data_queue_saturated_threshold=3400,
        queue_tick_ms_normal=50,
        queue_tick_ms_pressured=10,
        queue_tick_ms_saturated=1,
        queue_drain_max_events_normal=1200,
        queue_drain_max_events_pressured=2000,
        queue_drain_max_events_saturated=2600,
        queue_drain_max_time_ms_normal=8.0,
        queue_drain_max_time_ms_pressured=10.0,
        queue_drain_max_time_ms_saturated=12.0,
    ),
    monitor=MonitorRuntimePolicy(
        lines_per_poll_normal=2000,
        lines_per_poll_pressured=600,
        sleep_active_normal=0.05,
        sleep_active_pressured=0.08,
        sleep_active_saturated=0.12,
        sleep_idle_normal=0.5,
        sleep_idle_pressured=0.35,
        sleep_idle_saturated=0.12,
    ),
    import_=ImportRuntimePolicy(
        apply_frame_budget_ms=6.0,
        apply_mutation_batch_size=384,
    ),
    debug_unlock=DebugUnlockPolicy(
        click_target=7,
        window_seconds=3.0,
    ),
)
