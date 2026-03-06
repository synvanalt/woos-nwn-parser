"""Additional branch-focused tests for DataStore."""

from datetime import datetime, timedelta

import pytest

from app.storage import DataStore


def test_get_attack_stats_for_target_aggregates_multiple_attackers(data_store: DataStore) -> None:
    data_store.insert_attack_event("Woo", "Dragon", "hit")
    data_store.insert_attack_event("Woo", "Dragon", "critical_hit")
    data_store.insert_attack_event("Rogue", "Dragon", "miss")
    data_store.insert_attack_event("Mage", "Dragon", "miss")

    stats = data_store.get_attack_stats_for_target("Dragon")

    assert stats is not None
    assert stats["total_attacks"] == 4
    assert stats["hits"] == 1
    assert stats["crits"] == 1
    assert stats["misses"] == 2
    assert stats["hit_rate"] == 50.0


def test_get_attack_stats_for_target_returns_none_when_missing(data_store: DataStore) -> None:
    assert data_store.get_attack_stats_for_target("Missing") is None


def test_get_hit_rate_per_character_with_target_filter(data_store: DataStore) -> None:
    data_store.insert_attack_event("Woo", "Goblin", "hit")
    data_store.insert_attack_event("Woo", "Goblin", "miss")
    data_store.insert_attack_event("Woo", "Orc", "miss")
    data_store.insert_attack_event("Rogue", "Goblin", "critical_hit")

    hit_rates = data_store.get_hit_rate_per_character(target="Goblin")

    assert set(hit_rates) == {"Woo", "Rogue"}
    assert hit_rates["Woo"] == 50.0
    assert hit_rates["Rogue"] == 100.0


def test_get_dps_data_global_mode_without_start_time_uses_earliest(data_store: DataStore) -> None:
    t0 = datetime(2026, 1, 9, 12, 0, 0)
    t1 = t0 + timedelta(seconds=10)
    t2 = t0 + timedelta(seconds=20)

    data_store.update_dps_data("Woo", 100, t1, {"Fire": 100})
    data_store.update_dps_data("Rogue", 50, t2, {"Cold": 50})

    dps = data_store.get_dps_data(time_tracking_mode="global", global_start_time=None)
    by_character = {row["character"]: row for row in dps}

    assert set(by_character) == {"Woo", "Rogue"}
    assert by_character["Woo"]["dps"] == pytest.approx(10.0, abs=0.01)   # 100 / (20-10 -> 10, but global start=min=10)
    assert by_character["Rogue"]["dps"] == pytest.approx(5.0, abs=0.01)


def test_get_dps_breakdown_global_returns_empty_when_last_timestamp_missing(data_store: DataStore) -> None:
    ts = datetime(2026, 1, 9, 12, 0, 0)
    data_store.update_dps_data("Woo", 100, ts, {"Fire": 100})
    data_store.last_damage_timestamp = None

    assert data_store.get_dps_breakdown_by_type("Woo", time_tracking_mode="global", global_start_time=ts) == []


def test_get_dps_data_for_target_global_mode_without_start_time(data_store: DataStore) -> None:
    base = datetime(2026, 1, 9, 12, 0, 0)
    t_a = base + timedelta(seconds=10)
    t_b = base + timedelta(seconds=20)
    t_c = base + timedelta(seconds=30)

    # Same target, different attackers
    data_store.insert_damage_event("Goblin", "Fire", 0, 80, "Woo", t_a)
    data_store.insert_damage_event("Goblin", "Cold", 0, 40, "Rogue", t_b)
    # Different target should not affect Goblin target-start fallback
    data_store.insert_damage_event("Dragon", "Fire", 0, 999, "Mage", base)
    data_store.last_damage_timestamp = t_c

    dps = data_store.get_dps_data_for_target("Goblin", time_tracking_mode="global", global_start_time=None)
    by_character = {row["character"]: row for row in dps}

    assert set(by_character) == {"Woo", "Rogue"}
    # global_start_time for this target should be t_a (earliest Goblin hit)
    assert by_character["Woo"]["dps"] == pytest.approx(80 / 20, abs=0.01)
    assert by_character["Rogue"]["dps"] == pytest.approx(40 / 20, abs=0.01)


def test_get_earliest_timestamp_for_target_none_and_present(data_store: DataStore) -> None:
    assert data_store.get_earliest_timestamp_for_target("Goblin") is None

    t1 = datetime(2026, 1, 9, 12, 0, 10)
    t2 = datetime(2026, 1, 9, 12, 0, 20)
    data_store.insert_damage_event("Goblin", "Fire", 0, 10, "Woo", t2)
    data_store.insert_damage_event("Goblin", "Fire", 0, 10, "Rogue", t1)

    assert data_store.get_earliest_timestamp_for_target("Goblin") == t1


def test_damage_max_helpers_for_missing_and_existing_rows(data_store: DataStore) -> None:
    assert data_store.get_max_damage_for_target_and_type("Goblin", "Fire") == 0
    assert data_store.get_max_damage_from_events_for_target_and_type("Goblin", "Fire") == 0

    data_store.insert_damage_event("Goblin", "Fire", 0, 12, "Woo")
    data_store.insert_damage_event("Goblin", "Fire", 0, 33, "Woo")
    data_store.record_immunity("Goblin", "Fire", immunity_points=7, damage_dealt=33)

    assert data_store.get_max_damage_from_events_for_target_and_type("Goblin", "Fire") == 33
    assert data_store.get_max_damage_for_target_and_type("Goblin", "Fire") == 33
