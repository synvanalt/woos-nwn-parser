"""Target immunity read projections built from DataStore indices."""

from __future__ import annotations

from ...storage import DataStore


class ImmunityQueryService:
    """Build immunity summary rows from indexed damage and immunity state."""

    def __init__(self, data_store: DataStore) -> None:
        self.data_store = data_store
        self._cache_version = -1
        self._summary_cache: dict[str, tuple[dict[str, int | str | bool], ...]] = {}

    def _reset_caches_if_needed(self) -> None:
        version = self.data_store.version
        if self._cache_version == version:
            return
        self._cache_version = version
        self._summary_cache.clear()

    def get_target_damage_type_summary(self, target: str) -> list[dict[str, int | str | bool]]:
        self._reset_caches_if_needed()
        cached = self._summary_cache.get(target)
        if cached is not None:
            return [row.copy() for row in cached]

        with self.data_store.lock:
            damage_summary = self.data_store._damage_summary_by_target.get(target, {})
            immunity_summary = self.data_store.immunity_data.get(target, {})
            if not damage_summary and not immunity_summary:
                return []

            rows: list[dict[str, int | str | bool]] = []
            for damage_type in sorted(set(damage_summary) | set(immunity_summary)):
                damage_info = damage_summary.get(damage_type, {})
                immunity_info = immunity_summary.get(damage_type, {})
                max_event_damage = int(damage_info.get("max_damage", 0))
                max_immunity_damage = int(immunity_info.get("max_damage", 0))
                sample_count = int(immunity_info.get("sample_count", 0))
                rows.append(
                    {
                        "damage_type": damage_type,
                        "max_event_damage": max_event_damage,
                        "max_immunity_damage": max_immunity_damage,
                        "immunity_absorbed": int(immunity_info.get("max_immunity", 0)),
                        "sample_count": sample_count,
                        "suppress_temporary_full_immunity": (
                            sample_count > 0
                            and max_immunity_damage == 0
                            and max_event_damage > 0
                        ),
                    }
                )

        cached_rows = tuple(row.copy() for row in rows)
        self._summary_cache[target] = cached_rows
        return [row.copy() for row in cached_rows]
