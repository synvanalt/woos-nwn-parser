"""Shared immunity matching logic for live monitoring and file import."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, Iterable, List, Optional

from ..models import ImmunityMutation


@dataclass(slots=True, frozen=True)
class DamageObservation:
    """One unmatched damage component observation."""

    target: str
    damage_type: str
    damage_amount: int
    timestamp: datetime
    line_number: int


@dataclass(slots=True, frozen=True)
class ImmunityObservation:
    """One unmatched immunity observation."""

    target: str
    damage_type: str
    immunity_points: int
    timestamp: datetime
    line_number: int


class ImmunityMatcher:
    """Conservatively pair immunity lines with nearby damage observations."""

    def __init__(
        self,
        *,
        max_time_diff_seconds: float = 1.0,
        max_line_gap: int = 12,
    ) -> None:
        self.max_time_diff_seconds = float(max_time_diff_seconds)
        self.max_line_gap = max(1, int(max_line_gap))
        self._pending_damage: Dict[str, Dict[str, Deque[DamageObservation]]] = defaultdict(
            lambda: defaultdict(deque)
        )
        self._pending_immunity: Dict[str, Dict[str, Deque[ImmunityObservation]]] = defaultdict(
            lambda: defaultdict(deque)
        )
        self.latest_damage_by_target: Dict[str, Dict[str, object]] = {}

    @property
    def pending_immunity_queue(self) -> Dict[str, Dict[str, list[dict[str, object]]]]:
        """Compatibility/debug view of unmatched immunity observations."""
        result: Dict[str, Dict[str, list[dict[str, object]]]] = {}
        for target, by_type in self._pending_immunity.items():
            target_items: Dict[str, list[dict[str, object]]] = {}
            for damage_type, entries in by_type.items():
                if not entries:
                    continue
                target_items[damage_type] = [
                    {
                        "immunity": entry.immunity_points,
                        "timestamp": entry.timestamp,
                        "line_number": entry.line_number,
                    }
                    for entry in entries
                ]
            if target_items:
                result[target] = target_items
        return result

    def queue_immunity(
        self,
        *,
        target: str,
        damage_type: str,
        immunity_points: int,
        timestamp: datetime,
        line_number: int,
    ) -> list[ImmunityMutation]:
        """Register one immunity observation and return any completed matches."""
        observation = ImmunityObservation(
            target=target,
            damage_type=damage_type,
            immunity_points=int(immunity_points or 0),
            timestamp=timestamp,
            line_number=int(line_number),
        )
        return self._queue_immunity_observation(observation)

    def queue_damage_event(
        self,
        *,
        target: str,
        damage_types: Dict[str, int],
        timestamp: datetime,
        line_number: int,
        attacker: str = "",
    ) -> list[ImmunityMutation]:
        """Register one damage event and return any completed immunity matches."""
        normalized_damage_types = {damage_type: int(amount or 0) for damage_type, amount in damage_types.items()}
        self.latest_damage_by_target[target] = {
            "damage_types": normalized_damage_types.copy(),
            "timestamp": timestamp,
            "attacker": attacker,
            "line_number": int(line_number),
        }

        matches: list[ImmunityMutation] = []
        for damage_type, damage_amount in normalized_damage_types.items():
            observation = DamageObservation(
                target=target,
                damage_type=damage_type,
                damage_amount=damage_amount,
                timestamp=timestamp,
                line_number=int(line_number),
            )
            matches.extend(self._queue_damage_observation(observation))
        return matches

    def cleanup_stale_observations(
        self,
        *,
        now: Optional[datetime] = None,
        max_age_seconds: float = 5.0,
    ) -> None:
        """Remove pending observations that are too old to match."""
        cutoff = now or datetime.now()
        max_age = float(max_age_seconds)
        self._cleanup_direction(self._pending_damage, cutoff, max_age)
        self._cleanup_direction(self._pending_immunity, cutoff, max_age)

    def has_pending_immunity(self, *, target: str, damage_type: str) -> bool:
        """Return whether unmatched immunity observations exist for target/type."""
        return bool(self._pending_immunity.get(target, {}).get(damage_type))

    def _queue_damage_observation(self, observation: DamageObservation) -> list[ImmunityMutation]:
        queue = self._pending_immunity[observation.target][observation.damage_type]
        match_index = self._select_best_match_index(
            observation=observation,
            candidates=queue,
        )
        if match_index is not None:
            matched_immunity = queue[match_index]
            del queue[match_index]
            self._prune_empty_bucket(
                storage=self._pending_immunity,
                target=observation.target,
                damage_type=observation.damage_type,
            )
            return [
                ImmunityMutation(
                    target=observation.target,
                    damage_type=observation.damage_type,
                    immunity_points=matched_immunity.immunity_points,
                    damage_dealt=observation.damage_amount,
                )
            ]

        self._pending_damage[observation.target][observation.damage_type].append(observation)
        return []

    def _queue_immunity_observation(
        self, observation: ImmunityObservation
    ) -> list[ImmunityMutation]:
        queue = self._pending_damage[observation.target][observation.damage_type]
        match_index = self._select_best_match_index(
            observation=observation,
            candidates=queue,
        )
        if match_index is not None:
            matched_damage = queue[match_index]
            del queue[match_index]
            self._prune_empty_bucket(
                storage=self._pending_damage,
                target=observation.target,
                damage_type=observation.damage_type,
            )
            return [
                ImmunityMutation(
                    target=observation.target,
                    damage_type=observation.damage_type,
                    immunity_points=observation.immunity_points,
                    damage_dealt=matched_damage.damage_amount,
                )
            ]

        self._pending_immunity[observation.target][observation.damage_type].append(observation)
        return []

    def _select_best_match_index(
        self,
        *,
        observation: DamageObservation | ImmunityObservation,
        candidates: Iterable[DamageObservation] | Iterable[ImmunityObservation],
    ) -> Optional[int]:
        ranked: list[tuple[tuple[int, int, float, int], int]] = []
        for index, candidate in enumerate(candidates):
            if not self._is_eligible(observation, candidate):
                continue
            ranked.append((self._rank(observation, candidate), index))

        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0])
        best_rank = ranked[0][0]
        best_indexes = [index for rank, index in ranked if rank == best_rank]
        if len(best_indexes) != 1:
            return None
        return best_indexes[0]

    def _is_eligible(
        self,
        observation: DamageObservation | ImmunityObservation,
        candidate: DamageObservation | ImmunityObservation,
    ) -> bool:
        if observation.target != candidate.target or observation.damage_type != candidate.damage_type:
            return False

        time_diff = abs((observation.timestamp - candidate.timestamp).total_seconds())
        if time_diff > self.max_time_diff_seconds:
            return False

        line_gap = abs(observation.line_number - candidate.line_number)
        return line_gap <= self.max_line_gap

    @staticmethod
    def _rank(
        observation: DamageObservation | ImmunityObservation,
        candidate: DamageObservation | ImmunityObservation,
    ) -> tuple[int, int, float, int]:
        same_second_rank = 0 if observation.timestamp == candidate.timestamp else 1
        line_gap = abs(observation.line_number - candidate.line_number)
        time_diff = abs((observation.timestamp - candidate.timestamp).total_seconds())
        return (same_second_rank, line_gap, time_diff, candidate.line_number)

    @staticmethod
    def _prune_empty_bucket(
        *,
        storage: Dict[str, Dict[str, Deque[DamageObservation] | Deque[ImmunityObservation]]],
        target: str,
        damage_type: str,
    ) -> None:
        target_bucket = storage.get(target)
        if target_bucket is None:
            return
        if target_bucket.get(damage_type):
            return
        target_bucket.pop(damage_type, None)
        if not target_bucket:
            storage.pop(target, None)

    def _cleanup_direction(
        self,
        storage: Dict[str, Dict[str, Deque[DamageObservation] | Deque[ImmunityObservation]]],
        now: datetime,
        max_age_seconds: float,
    ) -> None:
        targets_to_remove: list[str] = []
        for target, by_type in storage.items():
            damage_types_to_remove: list[str] = []
            for damage_type, entries in by_type.items():
                filtered = deque(
                    entry
                    for entry in entries
                    if (now - entry.timestamp).total_seconds() <= max_age_seconds
                )
                by_type[damage_type] = filtered
                if not filtered:
                    damage_types_to_remove.append(damage_type)
            for damage_type in damage_types_to_remove:
                by_type.pop(damage_type, None)
            if not by_type:
                targets_to_remove.append(target)
        for target in targets_to_remove:
            storage.pop(target, None)
