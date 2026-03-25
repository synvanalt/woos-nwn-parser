"""Additional branch-focused tests for DataStore."""

from datetime import datetime, timedelta

import pytest

from app.services.queries import DpsQueryService
from app.storage import DataStore
from tests.helpers.store_mutations import apply, attack, damage_row, dps_update, immunity


def test_get_attack_stats_for_target_aggregates_multiple_attackers(data_store: DataStore) -> None:
    apply(
        data_store,
        attack(attacker="Woo", target="Dragon", outcome="hit"),
        attack(attacker="Woo", target="Dragon", outcome="critical_hit"),
        attack(attacker="Rogue", target="Dragon", outcome="miss"),
        attack(attacker="Mage", target="Dragon", outcome="miss"),
    )

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
    apply(
        data_store,
        attack(attacker="Woo", target="Goblin", outcome="hit"),
        attack(attacker="Woo", target="Goblin", outcome="miss"),
        attack(attacker="Woo", target="Orc", outcome="miss"),
        attack(attacker="Rogue", target="Goblin", outcome="critical_hit"),
    )

    hit_rates = data_store.get_hit_rate_per_character(target="Goblin")

    assert set(hit_rates) == {"Woo", "Rogue"}
    assert hit_rates["Woo"] == 50.0
    assert hit_rates["Rogue"] == 100.0


def test_get_dps_data_global_mode_without_start_time_uses_earliest(data_store: DataStore) -> None:
    t0 = datetime(2026, 1, 9, 12, 0, 0)
    t1 = t0 + timedelta(seconds=10)
    t2 = t0 + timedelta(seconds=20)

    apply(
        data_store,
        dps_update(attacker="Woo", total_damage=100, timestamp=t1, damage_types={"Fire": 100}),
        dps_update(attacker="Rogue", total_damage=50, timestamp=t2, damage_types={"Cold": 50}),
    )

    dps = DpsQueryService(data_store).get_dps_data(time_tracking_mode="global", global_start_time=None)
    by_character = {row.character: row for row in dps}

    assert set(by_character) == {"Woo", "Rogue"}
    assert by_character["Woo"].dps == pytest.approx(10.0, abs=0.01)   # 100 / (20-10 -> 10, but global start=min=10)
    assert by_character["Rogue"].dps == pytest.approx(5.0, abs=0.01)


def test_get_dps_breakdown_global_returns_empty_when_last_timestamp_missing(data_store: DataStore) -> None:
    ts = datetime(2026, 1, 9, 12, 0, 0)
    apply(data_store, dps_update(attacker="Woo", total_damage=100, timestamp=ts, damage_types={"Fire": 100}))
    data_store.last_damage_timestamp = None

    dps_query = DpsQueryService(data_store)
    dps_query.set_time_tracking_mode("global")
    dps_query.set_global_start_time(ts)
    assert dps_query.get_damage_type_breakdown("Woo") == []


def test_get_dps_data_for_target_global_mode_without_start_time(data_store: DataStore) -> None:
    base = datetime(2026, 1, 9, 12, 0, 0)
    t_a = base + timedelta(seconds=10)
    t_b = base + timedelta(seconds=20)
    t_c = base + timedelta(seconds=30)

    # Same target, different attackers
    apply(
        data_store,
        damage_row(target="Goblin", damage_type="Fire", total_damage=80, attacker="Woo", timestamp=t_a),
        damage_row(target="Goblin", damage_type="Cold", total_damage=40, attacker="Rogue", timestamp=t_b),
    )
    # Different target should not affect Goblin target-start fallback
    apply(data_store, damage_row(target="Dragon", damage_type="Fire", total_damage=999, attacker="Mage", timestamp=base))
    data_store.last_damage_timestamp = t_c

    dps = DpsQueryService(data_store).get_dps_data(
        target="Goblin",
        time_tracking_mode="global",
        global_start_time=None,
    )
    by_character = {row.character: row for row in dps}

    assert set(by_character) == {"Woo", "Rogue"}
    # global_start_time for this target should be t_a (earliest Goblin hit)
    assert by_character["Woo"].dps == pytest.approx(80 / 20, abs=0.01)
    assert by_character["Rogue"].dps == pytest.approx(40 / 20, abs=0.01)


def test_get_earliest_timestamp_for_target_none_and_present(data_store: DataStore) -> None:
    assert data_store.get_earliest_timestamp_for_target("Goblin") is None

    t1 = datetime(2026, 1, 9, 12, 0, 10)
    t2 = datetime(2026, 1, 9, 12, 0, 20)
    apply(
        data_store,
        damage_row(target="Goblin", damage_type="Fire", total_damage=10, attacker="Woo", timestamp=t2),
        damage_row(target="Goblin", damage_type="Fire", total_damage=10, attacker="Rogue", timestamp=t1),
    )

    assert data_store.get_earliest_timestamp_for_target("Goblin") == t1


def test_damage_max_helpers_for_missing_and_existing_rows(data_store: DataStore) -> None:
    assert data_store.get_max_damage_for_target_and_type("Goblin", "Fire") == 0
    assert data_store.get_max_damage_from_events_for_target_and_type("Goblin", "Fire") == 0

    apply(
        data_store,
        damage_row(target="Goblin", damage_type="Fire", total_damage=12, attacker="Woo"),
        damage_row(target="Goblin", damage_type="Fire", total_damage=33, attacker="Woo"),
        immunity(target="Goblin", damage_type="Fire", immunity_points=7, damage_dealt=33),
    )

    assert data_store.get_max_damage_from_events_for_target_and_type("Goblin", "Fire") == 33
    assert data_store.get_max_damage_for_target_and_type("Goblin", "Fire") == 33
