"""DPS read-side projections built from DataStore indices."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from ...storage import DataStore


class DpsQueryService:
    """Build DPS display rows and damage-type breakdowns from store indices."""

    def __init__(self, data_store: DataStore) -> None:
        self.data_store = data_store
        self.time_tracking_mode = "per_character"
        self.global_start_time: Optional[datetime] = None
        self._cache_version = -1
        self._dps_data_cache: dict[
            tuple[Optional[str], str, Optional[datetime]],
            tuple[dict[str, Any], ...],
        ] = {}
        self._dps_breakdowns_cache: dict[
            tuple[Optional[str], str, str, Optional[datetime]],
            tuple[dict[str, Any], ...],
        ] = {}
        self._hit_rate_cache: dict[Optional[str], dict[str, float]] = {}

    def _reset_caches_if_needed(self) -> None:
        version = self.data_store.version
        if self._cache_version == version:
            return
        self._cache_version = version
        self._dps_data_cache.clear()
        self._dps_breakdowns_cache.clear()
        self._hit_rate_cache.clear()

    def set_time_tracking_mode(self, mode: str) -> None:
        if mode not in ("per_character", "global"):
            raise ValueError(f"Invalid mode: {mode}")
        self.time_tracking_mode = mode
        if mode == "global" and self.global_start_time is None:
            self.global_start_time = self.data_store.get_earliest_timestamp()

    def set_global_start_time(self, timestamp: Optional[datetime]) -> None:
        self.global_start_time = timestamp

    def _resolve_global_start_time(
        self,
        *,
        target: Optional[str],
        global_start_time: Optional[datetime],
    ) -> Optional[datetime]:
        if global_start_time is not None:
            return global_start_time
        if target is None:
            return self.data_store.get_earliest_timestamp()
        return self.data_store.get_earliest_timestamp_for_target(target)

    @staticmethod
    def _copy_rows(rows: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
        return [row.copy() for row in rows]

    @staticmethod
    def _build_breakdown_rows(
        damage_by_type: Sequence[tuple[str, int]],
        time_seconds: float,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for damage_type, total_damage in damage_by_type:
            rows.append(
                {
                    "damage_type": damage_type,
                    "total_damage": total_damage,
                    "dps": total_damage / time_seconds,
                }
            )
        rows.sort(key=lambda row: row["total_damage"], reverse=True)
        return rows

    def _build_dps_rows(
        self,
        *,
        target: Optional[str],
        time_tracking_mode: str,
        global_start_time: Optional[datetime],
    ) -> list[dict[str, Any]]:
        resolved_global_start = self._resolve_global_start_time(
            target=target,
            global_start_time=global_start_time,
        )
        last_damage_timestamp = self.data_store.get_last_damage_timestamp()
        rows: list[dict[str, Any]] = []
        summaries = (
            self.data_store.get_dps_summaries()
            if target is None
            else self.data_store.get_target_dps_summaries(target)
        )

        if time_tracking_mode == "global":
            if resolved_global_start is None or last_damage_timestamp is None:
                return rows
            for summary in summaries:
                total_damage = int(summary.total_damage)
                if total_damage == 0:
                    continue
                time_delta = last_damage_timestamp - resolved_global_start
                time_seconds = max(time_delta.total_seconds(), 1)
                rows.append(
                    {
                        "character": summary.character,
                        "total_damage": total_damage,
                        "time_seconds": time_delta,
                        "dps": total_damage / time_seconds,
                        "breakdown_token": summary.breakdown_token,
                    }
                )
        else:
            if last_damage_timestamp is None and target is None:
                return rows
            for summary in summaries:
                total_damage = int(summary.total_damage)
                if total_damage == 0:
                    continue
                if target is None:
                    if last_damage_timestamp is None:
                        continue
                    time_delta = last_damage_timestamp - summary.first_timestamp
                else:
                    if summary.last_timestamp is None:
                        continue
                    time_delta = summary.last_timestamp - summary.first_timestamp
                time_seconds = max(time_delta.total_seconds(), 1)
                rows.append(
                    {
                        "character": summary.character,
                        "total_damage": total_damage,
                        "time_seconds": time_delta,
                        "dps": total_damage / time_seconds,
                        "breakdown_token": summary.breakdown_token,
                    }
                )

        rows.sort(key=lambda row: row["dps"], reverse=True)
        return rows

    def get_dps_data(
        self,
        *,
        target: Optional[str] = None,
        time_tracking_mode: Optional[str] = None,
        global_start_time: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        self._reset_caches_if_needed()
        effective_mode = time_tracking_mode or self.time_tracking_mode
        effective_start = global_start_time if global_start_time is not None else self.global_start_time
        resolved_global_start = self._resolve_global_start_time(
            target=target,
            global_start_time=effective_start,
        )
        cache_key = (target, effective_mode, resolved_global_start)
        cached_rows = self._dps_data_cache.get(cache_key)
        if cached_rows is not None:
            return self._copy_rows(cached_rows)

        rows = self._build_dps_rows(
            target=target,
            time_tracking_mode=effective_mode,
            global_start_time=effective_start,
        )
        cached_rows = tuple(row.copy() for row in rows)
        self._dps_data_cache[cache_key] = cached_rows
        return self._copy_rows(cached_rows)

    def get_hit_rate_for_damage_dealers(self, *, target: Optional[str] = None) -> dict[str, float]:
        self._reset_caches_if_needed()
        cached = self._hit_rate_cache.get(target)
        if cached is not None:
            return dict(cached)
        hit_rates = self.data_store.get_hit_rate_for_damage_dealers(target=target)
        self._hit_rate_cache[target] = dict(hit_rates)
        return dict(hit_rates)

    def get_dps_display_data(self, target_filter: str = "All") -> list[dict[str, Any]]:
        if target_filter == "All":
            rows = self.get_dps_data()
            hit_rates = self.get_hit_rate_for_damage_dealers()
        else:
            rows = self.get_dps_data(target=target_filter)
            hit_rates = self.get_hit_rate_for_damage_dealers(target=target_filter)

        for row in rows:
            row["hit_rate"] = hit_rates.get(str(row["character"]), 0.0)
        return rows

    def get_damage_type_breakdowns(
        self,
        characters: list[str],
        target_filter: str = "All",
    ) -> dict[str, list[dict[str, Any]]]:
        self._reset_caches_if_needed()
        unique_characters = list(dict.fromkeys(characters))
        result: dict[str, list[dict[str, Any]]] = {character: [] for character in unique_characters}
        if not unique_characters:
            return result

        target = None if target_filter == "All" else target_filter
        effective_start = self.global_start_time
        resolved_global_start = self._resolve_global_start_time(
            target=target,
            global_start_time=effective_start,
        )

        summaries = (
            {
                summary.character: summary
                for summary in self.data_store.get_dps_summaries()
            }
            if target is None
            else {
                summary.character: summary
                for summary in self.data_store.get_target_dps_summaries(target)
            }
        )
        last_damage_timestamp = self.data_store.get_last_damage_timestamp()

        for character in unique_characters:
            cache_key = (
                target,
                character,
                self.time_tracking_mode,
                resolved_global_start,
            )
            cached_rows = self._dps_breakdowns_cache.get(cache_key)
            if cached_rows is None:
                summary = summaries.get(character)
                if summary is None or int(summary.total_damage) == 0:
                    rows: list[dict[str, Any]] = []
                elif self.time_tracking_mode == "global":
                    if resolved_global_start is None or last_damage_timestamp is None:
                        rows = []
                    else:
                        time_seconds = max(
                            (last_damage_timestamp - resolved_global_start).total_seconds(),
                            1,
                        )
                        rows = self._build_breakdown_rows(
                            summary.damage_by_type,
                            time_seconds,
                        )
                elif target is None:
                    if last_damage_timestamp is None:
                        rows = []
                    else:
                        time_seconds = max(
                            (last_damage_timestamp - summary.first_timestamp).total_seconds(),
                            1,
                        )
                        rows = self._build_breakdown_rows(
                            summary.damage_by_type,
                            time_seconds,
                        )
                else:
                    if summary.last_timestamp is None:
                        rows = []
                    else:
                        time_seconds = max(
                            (
                                summary.last_timestamp - summary.first_timestamp
                            ).total_seconds(),
                            1,
                        )
                        rows = self._build_breakdown_rows(
                            summary.damage_by_type,
                            time_seconds,
                        )
                cached_rows = tuple(row.copy() for row in rows)
                self._dps_breakdowns_cache[cache_key] = cached_rows
            result[character] = self._copy_rows(cached_rows)
        return result

    def get_damage_type_breakdown(
        self,
        character: str,
        target_filter: str = "All",
    ) -> list[dict[str, Any]]:
        return self.get_damage_type_breakdowns([character], target_filter).get(character, [])
