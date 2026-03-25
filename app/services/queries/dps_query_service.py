"""DPS read-side projections built from DataStore indices."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from ...storage import DataStore, DpsProjectionSnapshot
from .models import DpsBreakdownRow, DpsRow


class DpsQueryService:
    """Build DPS display rows and damage-type breakdowns from store indices."""

    def __init__(self, data_store: DataStore) -> None:
        self.data_store = data_store
        self.time_tracking_mode = "per_character"
        self.global_start_time: Optional[datetime] = None
        self._cache_version = -1
        self._dps_data_cache: dict[
            tuple[Optional[str], str, Optional[datetime]],
            tuple[DpsRow, ...],
        ] = {}
        self._dps_breakdowns_cache: dict[
            tuple[Optional[str], str, str, Optional[datetime]],
            tuple[DpsBreakdownRow, ...],
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
        global_start_time: Optional[datetime],
        projection: DpsProjectionSnapshot,
    ) -> Optional[datetime]:
        if global_start_time is not None:
            return global_start_time
        return projection.earliest_timestamp

    @staticmethod
    def _build_breakdown_rows(
        damage_by_type: Sequence[tuple[str, int]],
        time_seconds: float,
    ) -> list[DpsBreakdownRow]:
        rows: list[DpsBreakdownRow] = []
        for damage_type, total_damage in damage_by_type:
            rows.append(
                DpsBreakdownRow(
                    damage_type=damage_type,
                    total_damage=total_damage,
                    dps=total_damage / time_seconds,
                )
            )
        rows.sort(key=lambda row: row.total_damage, reverse=True)
        return rows

    def _build_dps_rows(
        self,
        *,
        time_tracking_mode: str,
        global_start_time: Optional[datetime],
        projection: DpsProjectionSnapshot,
    ) -> list[DpsRow]:
        resolved_global_start = self._resolve_global_start_time(
            global_start_time=global_start_time,
            projection=projection,
        )
        last_damage_timestamp = projection.last_damage_timestamp
        rows: list[DpsRow] = []
        summaries = projection.summaries

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
                    DpsRow(
                        character=summary.character,
                        total_damage=total_damage,
                        time_seconds=time_delta,
                        dps=total_damage / time_seconds,
                        breakdown_token=summary.breakdown_token,
                    )
                )
        else:
            if last_damage_timestamp is None and global_start_time is None and projection.earliest_timestamp is None:
                return rows
            for summary in summaries:
                total_damage = int(summary.total_damage)
                if total_damage == 0:
                    continue
                if summary.last_timestamp is None:
                    if last_damage_timestamp is None:
                        continue
                    time_delta = last_damage_timestamp - summary.first_timestamp
                else:
                    time_delta = summary.last_timestamp - summary.first_timestamp
                time_seconds = max(time_delta.total_seconds(), 1)
                rows.append(
                    DpsRow(
                        character=summary.character,
                        total_damage=total_damage,
                        time_seconds=time_delta,
                        dps=total_damage / time_seconds,
                        breakdown_token=summary.breakdown_token,
                    )
                )

        rows.sort(key=lambda row: row.dps, reverse=True)
        return rows

    def get_dps_data(
        self,
        *,
        target: Optional[str] = None,
        time_tracking_mode: Optional[str] = None,
        global_start_time: Optional[datetime] = None,
    ) -> list[DpsRow]:
        self._reset_caches_if_needed()
        effective_mode = time_tracking_mode or self.time_tracking_mode
        effective_start = global_start_time if global_start_time is not None else self.global_start_time
        projection = self.data_store.get_dps_projection_snapshot(target)
        resolved_global_start = self._resolve_global_start_time(
            global_start_time=effective_start,
            projection=projection,
        )
        cache_key = (target, effective_mode, resolved_global_start)
        cached_rows = self._dps_data_cache.get(cache_key)
        if cached_rows is not None:
            return list(cached_rows)

        rows = self._build_dps_rows(
            time_tracking_mode=effective_mode,
            global_start_time=effective_start,
            projection=projection,
        )
        cached_rows = tuple(rows)
        self._dps_data_cache[cache_key] = cached_rows
        return list(cached_rows)

    def get_hit_rate_for_damage_dealers(self, *, target: Optional[str] = None) -> dict[str, float]:
        self._reset_caches_if_needed()
        cached = self._hit_rate_cache.get(target)
        if cached is not None:
            return dict(cached)
        hit_rates = self.data_store.get_hit_rate_for_damage_dealers(target=target)
        self._hit_rate_cache[target] = dict(hit_rates)
        return dict(hit_rates)

    def get_dps_display_data(self, target_filter: str = "All") -> list[DpsRow]:
        if target_filter == "All":
            rows = self.get_dps_data()
            hit_rates = self.get_hit_rate_for_damage_dealers()
        else:
            rows = self.get_dps_data(target=target_filter)
            hit_rates = self.get_hit_rate_for_damage_dealers(target=target_filter)

        return [
            DpsRow(
                character=row.character,
                total_damage=row.total_damage,
                time_seconds=row.time_seconds,
                dps=row.dps,
                breakdown_token=row.breakdown_token,
                hit_rate=hit_rates.get(row.character, 0.0),
            )
            for row in rows
        ]

    def get_damage_type_breakdowns(
        self,
        characters: list[str],
        target_filter: str = "All",
    ) -> dict[str, list[DpsBreakdownRow]]:
        self._reset_caches_if_needed()
        unique_characters = list(dict.fromkeys(characters))
        result: dict[str, list[DpsBreakdownRow]] = {character: [] for character in unique_characters}
        if not unique_characters:
            return result

        target = None if target_filter == "All" else target_filter
        effective_start = self.global_start_time
        projection = self.data_store.get_dps_projection_snapshot(target)
        resolved_global_start = self._resolve_global_start_time(
            global_start_time=effective_start,
            projection=projection,
        )
        summaries = {summary.character: summary for summary in projection.summaries}
        last_damage_timestamp = projection.last_damage_timestamp

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
                    rows: list[DpsBreakdownRow] = []
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
                cached_rows = tuple(rows)
                self._dps_breakdowns_cache[cache_key] = cached_rows
            result[character] = list(cached_rows)
        return result

    def get_damage_type_breakdown(
        self,
        character: str,
        target_filter: str = "All",
    ) -> list[DpsBreakdownRow]:
        return self.get_damage_type_breakdowns([character], target_filter).get(character, [])
