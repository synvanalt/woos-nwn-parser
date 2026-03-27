"""Unit tests for default app runtime policy."""

from app.ui.runtime_config import DEFAULT_APP_RUNTIME_CONFIG


def test_default_runtime_config_preserves_existing_policy_values() -> None:
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.data_queue_maxsize == 4000
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.data_queue_pressured_threshold == 2000
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.data_queue_saturated_threshold == 3400
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.queue_tick_ms_normal == 50
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.queue_tick_ms_pressured == 10
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.queue_tick_ms_saturated == 1
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.queue_drain_max_events_normal == 1200
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.queue_drain_max_events_pressured == 2000
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.queue_drain_max_events_saturated == 2600
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.queue_drain_max_time_ms_normal == 8.0
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.queue_drain_max_time_ms_pressured == 10.0
    assert DEFAULT_APP_RUNTIME_CONFIG.queue.queue_drain_max_time_ms_saturated == 12.0
    assert DEFAULT_APP_RUNTIME_CONFIG.monitor.lines_per_poll_normal == 2000
    assert DEFAULT_APP_RUNTIME_CONFIG.monitor.lines_per_poll_pressured == 600
    assert DEFAULT_APP_RUNTIME_CONFIG.monitor.sleep_active_normal == 0.05
    assert DEFAULT_APP_RUNTIME_CONFIG.monitor.sleep_active_pressured == 0.08
    assert DEFAULT_APP_RUNTIME_CONFIG.monitor.sleep_active_saturated == 0.12
    assert DEFAULT_APP_RUNTIME_CONFIG.monitor.sleep_idle_normal == 0.5
    assert DEFAULT_APP_RUNTIME_CONFIG.monitor.sleep_idle_pressured == 0.35
    assert DEFAULT_APP_RUNTIME_CONFIG.monitor.sleep_idle_saturated == 0.12
    assert DEFAULT_APP_RUNTIME_CONFIG.import_.apply_frame_budget_ms == 6.0
    assert DEFAULT_APP_RUNTIME_CONFIG.import_.apply_mutation_batch_size == 384
    assert DEFAULT_APP_RUNTIME_CONFIG.debug_unlock.click_target == 7
    assert DEFAULT_APP_RUNTIME_CONFIG.debug_unlock.window_seconds == 3.0
    assert DEFAULT_APP_RUNTIME_CONFIG.debug_unlock.dps_tab_text == "Damage Per Second"
    assert DEFAULT_APP_RUNTIME_CONFIG.debug_unlock.debug_tab_text == "Debug Console"
