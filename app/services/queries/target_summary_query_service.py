"""Target summary read projections built from DataStore indices."""

from __future__ import annotations

from ...storage import DataStore


class TargetSummaryQueryService:
    """Build target summary rows from store-owned indices."""

    def __init__(self, data_store: DataStore) -> None:
        self.data_store = data_store
        self._cache_version = -1
        self._summary_cache: tuple[dict[str, str], ...] | None = None

    def _reset_caches_if_needed(self) -> None:
        version = self.data_store.version
        if self._cache_version == version:
            return
        self._cache_version = version
        self._summary_cache = None

    def get_all_targets_summary(self) -> list[dict[str, str]]:
        self._reset_caches_if_needed()
        if self._summary_cache is not None:
            return [row.copy() for row in self._summary_cache]

        rows: list[dict[str, str]] = []
        for snapshot in self.data_store.get_all_target_summary_snapshots():
            rows.append(
                {
                    "target": snapshot.target,
                    "ab": snapshot.ab_display,
                    "ac": snapshot.ac_display,
                    "fortitude": (
                        str(snapshot.fortitude) if snapshot.fortitude is not None else "-"
                    ),
                    "reflex": str(snapshot.reflex) if snapshot.reflex is not None else "-",
                    "will": str(snapshot.will) if snapshot.will is not None else "-",
                    "damage_taken": str(snapshot.damage_taken),
                }
            )

        self._summary_cache = tuple(row.copy() for row in rows)
        return [row.copy() for row in self._summary_cache]
