"""Unit tests for immunity query display-row preparation."""

from dataclasses import FrozenInstanceError

import pytest

import app.services.queries.immunity_query_service as immunity_query_module
from app.services.queries import ImmunityQueryService
from app.storage import DataStore
from tests.helpers.store_mutations import apply, damage_row, immunity


@pytest.fixture
def query_service() -> tuple[DataStore, ImmunityQueryService]:
    store = DataStore()
    return store, ImmunityQueryService(store)


def test_get_target_immunity_display_rows_shows_zero_damage_full_immunity(
    query_service: tuple[DataStore, ImmunityQueryService],
) -> None:
    store, service = query_service
    apply(
        store,
        damage_row(target="DRAMMAGAR", damage_type="Acid", total_damage=0, attacker="Woo"),
        immunity(target="DRAMMAGAR", damage_type="Acid", immunity_points=50, damage_dealt=0),
    )

    rows = service.get_target_immunity_display_rows("DRAMMAGAR", True)

    assert rows == [immunity_query_module.ImmunityDisplayRow("Acid", "0", "50", "100%", "1")]


def test_get_target_immunity_display_rows_uses_highest_absorbed_for_zero_damage_tie(
    query_service: tuple[DataStore, ImmunityQueryService],
) -> None:
    store, service = query_service
    apply(
        store,
        damage_row(target="DRAMMAGAR", damage_type="Acid", total_damage=0, attacker="Woo"),
        immunity(target="DRAMMAGAR", damage_type="Acid", immunity_points=50, damage_dealt=0),
        immunity(target="DRAMMAGAR", damage_type="Acid", immunity_points=55, damage_dealt=0),
    )

    rows = service.get_target_immunity_display_rows("DRAMMAGAR", True)

    assert rows == [immunity_query_module.ImmunityDisplayRow("Acid", "0", "55", "100%", "2")]


def test_get_target_immunity_display_rows_suppresses_temporary_full_immunity(
    query_service: tuple[DataStore, ImmunityQueryService],
) -> None:
    store, service = query_service
    apply(
        store,
        damage_row(target="DRAMMAGAR", damage_type="Acid", total_damage=45, attacker="Woo"),
        immunity(target="DRAMMAGAR", damage_type="Acid", immunity_points=50, damage_dealt=0),
    )

    rows = service.get_target_immunity_display_rows("DRAMMAGAR", True)

    assert rows == [immunity_query_module.ImmunityDisplayRow("Acid", "45", "-", "-", "1")]


def test_get_target_immunity_display_rows_uses_best_effort_percentage_when_needed(
    query_service: tuple[DataStore, ImmunityQueryService],
) -> None:
    store, service = query_service
    apply(
        store,
        damage_row(target="Goblin", damage_type="Physical", total_damage=146, attacker="Woo"),
        immunity(target="Goblin", damage_type="Physical", immunity_points=33, damage_dealt=146),
    )

    rows = service.get_target_immunity_display_rows("Goblin", True)

    assert rows == [
        immunity_query_module.ImmunityDisplayRow("Physical", "146", "33", "18%", "1")
    ]


def test_get_target_immunity_display_rows_keeps_last_known_pct_when_parse_disabled(
    query_service: tuple[DataStore, ImmunityQueryService],
) -> None:
    store, service = query_service
    apply(
        store,
        damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
        immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50),
    )

    service.get_target_immunity_display_rows("Goblin", True)
    rows = service.get_target_immunity_display_rows("Goblin", False)

    assert rows == [immunity_query_module.ImmunityDisplayRow("Fire", "50", "10", "17%", "1")]


def test_parse_disabled_cache_refreshes_after_parse_enabled_learns_percentage(
    query_service: tuple[DataStore, ImmunityQueryService],
) -> None:
    store, service = query_service
    apply(
        store,
        damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
        immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50),
    )

    parse_off_before = service.get_target_immunity_display_rows("Goblin", False)
    parse_on = service.get_target_immunity_display_rows("Goblin", True)
    parse_off_after = service.get_target_immunity_display_rows("Goblin", False)

    assert parse_off_before == [
        immunity_query_module.ImmunityDisplayRow("Fire", "50", "10", "-", "1")
    ]
    assert parse_on == [
        immunity_query_module.ImmunityDisplayRow("Fire", "50", "10", "17%", "1")
    ]
    assert parse_off_after == [
        immunity_query_module.ImmunityDisplayRow("Fire", "50", "10", "17%", "1")
    ]


def test_get_target_immunity_display_rows_returns_dash_when_percentage_unknown(
    query_service: tuple[DataStore, ImmunityQueryService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service = query_service
    apply(
        store,
        damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
        immunity(target="Goblin", damage_type="Fire", immunity_points=10, damage_dealt=50),
    )
    monkeypatch.setattr(
        immunity_query_module,
        "calculate_immunity_percentage",
        lambda *_args, **_kwargs: None,
    )

    rows = service.get_target_immunity_display_rows("Goblin", True)

    assert rows == [immunity_query_module.ImmunityDisplayRow("Fire", "50", "10", "-", "1")]


def test_get_target_immunity_display_rows_returns_immutable_cached_rows(
    query_service: tuple[DataStore, ImmunityQueryService],
) -> None:
    store, service = query_service
    apply(
        store,
        damage_row(target="Goblin", damage_type="Fire", total_damage=50, attacker="Woo"),
    )

    rows = service.get_target_immunity_display_rows("Goblin", False)

    with pytest.raises(FrozenInstanceError):
        rows[0].max_damage_display = "999"  # type: ignore[misc]
