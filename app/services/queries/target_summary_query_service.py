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

        with self.data_store.lock:
            targets = self.data_store._get_sorted_targets_locked()
            rows: list[dict[str, str]] = []
            for target in targets:
                ab_display = "-"
                if target in self.data_store._target_attack_bonus_by_name:
                    ab_display = self.data_store._target_attack_bonus_by_name[target].get_bonus_display()

                ac_display = "-"
                if target in self.data_store._target_ac_by_name:
                    ac_display = self.data_store._target_ac_by_name[target].get_ac_estimate()

                fort_display = "-"
                ref_display = "-"
                will_display = "-"
                if target in self.data_store._target_saves_by_name:
                    saves = self.data_store._target_saves_by_name[target]
                    fort_display = str(saves.fortitude) if saves.fortitude is not None else "-"
                    ref_display = str(saves.reflex) if saves.reflex is not None else "-"
                    will_display = str(saves.will) if saves.will is not None else "-"

                rows.append(
                    {
                        "target": target,
                        "ab": ab_display,
                        "ac": ac_display,
                        "fortitude": fort_display,
                        "reflex": ref_display,
                        "will": will_display,
                        "damage_taken": str(self.data_store._damage_taken_by_target.get(target, 0)),
                    }
                )

        self._summary_cache = tuple(row.copy() for row in rows)
        return [row.copy() for row in self._summary_cache]
