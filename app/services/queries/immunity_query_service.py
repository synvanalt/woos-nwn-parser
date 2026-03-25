"""Target immunity read projections built from DataStore indices."""

from __future__ import annotations

from ...storage import DataStore
from .models import ImmunitySummaryRow


class ImmunityQueryService:
    """Build immunity summary rows from indexed damage and immunity state."""

    def __init__(self, data_store: DataStore) -> None:
        self.data_store = data_store
        self._cache_version = -1
        self._summary_cache: dict[str, tuple[ImmunitySummaryRow, ...]] = {}

    def _reset_caches_if_needed(self) -> None:
        version = self.data_store.version
        if self._cache_version == version:
            return
        self._cache_version = version
        self._summary_cache.clear()

    def get_target_damage_type_summary(self, target: str) -> list[ImmunitySummaryRow]:
        self._reset_caches_if_needed()
        cached = self._summary_cache.get(target)
        if cached is not None:
            return list(cached)

        snapshots = self.data_store.get_target_damage_type_snapshots(target)
        if not snapshots:
            return []

        rows: list[ImmunitySummaryRow] = []
        for snapshot in snapshots:
            rows.append(
                ImmunitySummaryRow(
                    damage_type=snapshot.damage_type,
                    max_event_damage=snapshot.max_event_damage,
                    max_immunity_damage=snapshot.max_immunity_damage,
                    immunity_absorbed=snapshot.immunity_absorbed,
                    sample_count=snapshot.sample_count,
                    suppress_temporary_full_immunity=(
                        snapshot.sample_count > 0
                        and snapshot.max_immunity_damage == 0
                        and snapshot.max_event_damage > 0
                    ),
                )
            )

        cached_rows = tuple(rows)
        self._summary_cache[target] = cached_rows
        return list(cached_rows)
