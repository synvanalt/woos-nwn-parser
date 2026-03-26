"""Target immunity read projections built from DataStore indices."""

from __future__ import annotations

from ...storage import DataStore, TargetDamageTypeSnapshot
from ...utils import calculate_immunity_percentage
from .models import ImmunityDisplayRow


class ImmunityQueryService:
    """Build prepared immunity display rows from indexed damage and immunity state."""

    def __init__(self, data_store: DataStore) -> None:
        self.data_store = data_store
        self._cache_version = -1
        self._display_cache: dict[tuple[str, bool], tuple[ImmunityDisplayRow, ...]] = {}
        self._immunity_pct_cache: dict[str, dict[str, int | None]] = {}

    def _reset_caches_if_needed(self) -> None:
        version = self.data_store.version
        if self._cache_version == version:
            return
        self._cache_version = version
        self._display_cache.clear()

    def get_target_immunity_display_rows(
        self,
        target: str,
        parse_immunity: bool,
    ) -> list[ImmunityDisplayRow]:
        self._reset_caches_if_needed()
        cache_key = (target, parse_immunity)
        cached = self._display_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        remembered_pcts = self._immunity_pct_cache.setdefault(target, {})
        rows: list[ImmunityDisplayRow] = []
        for snapshot in self.data_store.get_target_damage_type_snapshots(target):
            suppress_temporary_full_immunity = self._should_suppress_temporary_full_immunity(
                snapshot
            )
            max_damage = snapshot.max_event_damage
            if (
                parse_immunity
                and snapshot.sample_count > 0
                and not suppress_temporary_full_immunity
            ):
                max_damage = snapshot.max_immunity_damage

            if (
                parse_immunity
                and snapshot.sample_count > 0
                and not suppress_temporary_full_immunity
            ):
                max_damage_display = str(max_damage)
                absorbed_display = str(snapshot.immunity_absorbed)
            elif parse_immunity and suppress_temporary_full_immunity:
                max_damage_display = str(max_damage)
                absorbed_display = "-"
            else:
                max_damage_display = str(max_damage) if max_damage > 0 else "-"
                absorbed_display = (
                    str(snapshot.immunity_absorbed) if snapshot.immunity_absorbed > 0 else "-"
                )

            samples_display = str(snapshot.sample_count) if snapshot.sample_count > 0 else "-"
            immunity_pct_display = self._build_immunity_pct_display(
                remembered_pcts=remembered_pcts,
                snapshot=snapshot,
                parse_immunity=parse_immunity,
                suppress_temporary_full_immunity=suppress_temporary_full_immunity,
                max_damage=max_damage,
            )
            rows.append(
                ImmunityDisplayRow(
                    damage_type=snapshot.damage_type,
                    max_damage_display=max_damage_display,
                    absorbed_display=absorbed_display,
                    immunity_pct_display=immunity_pct_display,
                    samples_display=samples_display,
                )
            )

        cached_rows = tuple(rows)
        self._display_cache[cache_key] = cached_rows
        return list(cached_rows)

    def clear_caches(self) -> None:
        """Clear versioned row caches and remembered percentage displays."""
        self._cache_version = -1
        self._display_cache.clear()
        self._immunity_pct_cache.clear()

    @staticmethod
    def _should_suppress_temporary_full_immunity(snapshot: TargetDamageTypeSnapshot) -> bool:
        """Return whether a zero-damage-only full absorb should be hidden in display rows."""
        return (
            snapshot.sample_count > 0
            and snapshot.max_immunity_damage == 0
            and snapshot.max_event_damage > 0
        )

    @staticmethod
    def _build_immunity_pct_display(
        *,
        remembered_pcts: dict[str, int | None],
        snapshot: TargetDamageTypeSnapshot,
        parse_immunity: bool,
        suppress_temporary_full_immunity: bool,
        max_damage: int,
    ) -> str:
        cached_pct = remembered_pcts.get(snapshot.damage_type)
        if not parse_immunity:
            if cached_pct is None:
                return "-"
            return f"{cached_pct}%"

        if suppress_temporary_full_immunity:
            remembered_pcts[snapshot.damage_type] = None
            return "-"

        if snapshot.sample_count > 0 and max_damage == 0:
            remembered_pcts[snapshot.damage_type] = 100
            return "100%"

        if max_damage > 0 and snapshot.immunity_absorbed > 0:
            immunity_pct = calculate_immunity_percentage(max_damage, snapshot.immunity_absorbed)
            remembered_pcts[snapshot.damage_type] = immunity_pct
            if immunity_pct is not None:
                return f"{immunity_pct}%"
            return "-"

        if cached_pct is None:
            return "-"
        return f"{cached_pct}%"
