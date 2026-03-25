"""In-memory data storage for Woo's NWN Parser.

This module provides the DataStore class that manages all application data
using Python dataclasses instead of a database, providing session-only storage.
"""

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from .models import (
    AttackEvent,
    AttackMutation,
    DamageEvent,
    DamageMutation,
    EnemyAC,
    EnemySaves,
    EpicDodgeMutation,
    ImmunityMutation,
    SaveMutation,
    StoreMutation,
    TargetAttackBonus,
)


@dataclass(frozen=True, slots=True)
class DpsSummarySnapshot:
    """Immutable indexed DPS summary exposed to query services."""

    character: str
    total_damage: int
    first_timestamp: datetime
    last_timestamp: Optional[datetime]
    damage_by_type: tuple[tuple[str, int], ...]
    breakdown_token: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DpsProjectionSnapshot:
    """Immutable atomic DPS projection state exposed to query services."""

    last_damage_timestamp: Optional[datetime]
    earliest_timestamp: Optional[datetime]
    summaries: tuple[DpsSummarySnapshot, ...]


@dataclass(frozen=True, slots=True)
class TargetDamageTypeSnapshot:
    """Immutable indexed damage/immunity summary for one target damage type."""

    damage_type: str
    max_event_damage: int
    max_immunity_damage: int
    immunity_absorbed: int
    sample_count: int


@dataclass(frozen=True, slots=True)
class TargetSummarySnapshot:
    """Immutable target-summary snapshot exposed to query services."""

    target: str
    ab_display: str
    ac_display: str
    fortitude: Optional[int]
    reflex: Optional[int]
    will: Optional[int]
    damage_taken: int


class DataStore:
    """In-memory data store using dataclasses.

    Owns mutable session state, write-side mutations, and indexed primitive reads.
    All data is stored in memory and lost when the app closes (session-only).
    """

    DEFAULT_MAX_EVENTS_HISTORY = 200000
    DEFAULT_MAX_ATTACKS_HISTORY = 200000

    def __init__(
        self,
        max_events_history: int | None = None,
        max_attacks_history: int | None = None,
    ) -> None:
        """Initialize the data store."""
        self.max_events_history = self._normalize_history_limit(
            max_events_history,
            self.DEFAULT_MAX_EVENTS_HISTORY,
        )
        self.max_attacks_history = self._normalize_history_limit(
            max_attacks_history,
            self.DEFAULT_MAX_ATTACKS_HISTORY,
        )
        self.events: Deque[DamageEvent] = deque(maxlen=self.max_events_history)
        self.attacks: Deque[AttackEvent] = deque(maxlen=self.max_attacks_history)
        self.lock = threading.RLock()
        # Version counter for change detection (incremented on data modifications)
        self._version: int = 0
        # DPS tracking: character_name -> {'damage': total, 'first_timestamp': datetime, 'last_timestamp': datetime, 'damage_by_type': {type: amount}}
        self.dps_data: Dict[str, Dict] = {}
        # Global timestamp of the most recent damage dealt by ANY character
        self.last_damage_timestamp: Optional[datetime] = None
        # Immunity tracking: target -> damage_type -> {max_immunity: int, max_damage: int, sample_count: int}
        # This is separate from damage events to avoid double-counting while still tracking immunity data
        self.immunity_data: Dict[str, Dict[str, Dict[str, int]]] = {}
        # Cached set of all targets for fast lookup (updated on insert)
        self._targets_cache: set = set()
        # Cached set of damage dealers for fast lookup
        self._damage_dealers_cache: set = set()
        self._damage_taken_by_target: Dict[str, int] = {}
        self._attack_stats_by_attacker: Dict[str, Dict[str, int]] = {}
        self._attack_stats_by_target: Dict[str, Dict[str, int]] = {}
        self._attack_stats_by_attacker_target: Dict[Tuple[str, str], Dict[str, int]] = {}
        self._damage_summary_by_target: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._damage_dealers_by_target: Dict[str, set[str]] = {}
        self._dps_by_attacker_target: Dict[Tuple[str, str], Dict] = {}
        self._dps_breakdown_token_by_character: Dict[str, tuple[tuple[str, int], ...]] = {}
        self._dps_breakdown_dirty_characters: set[str] = set()
        self._dps_breakdown_token_by_attacker_target: Dict[
            Tuple[str, str], tuple[tuple[str, int], ...]
        ] = {}
        self._dps_breakdown_dirty_attacker_target: set[Tuple[str, str]] = set()
        self._earliest_timestamp: Optional[datetime] = None
        self._earliest_timestamp_by_target: Dict[str, datetime] = {}
        self._all_damage_types_cache: set[str] = set()
        self._sorted_targets_cache: tuple[str, ...] = ()
        self._sorted_targets_dirty: bool = False
        self._target_stats_cache: Dict[str, Dict[str, int]] = {}
        self._target_ac_by_name: Dict[str, EnemyAC] = {}
        self._target_saves_by_name: Dict[str, EnemySaves] = {}
        self._target_attack_bonus_by_name: Dict[str, TargetAttackBonus] = {}

    @staticmethod
    def _normalize_history_limit(value: int | None, default: int) -> int:
        """Clamp a configured raw-history retention limit to a safe integer."""
        if value is None:
            return default
        return max(1, int(value))

    @property
    def version(self) -> int:
        """Get the current data version for change detection.

        This version is incremented on every data modification, allowing
        callers to efficiently detect when data has changed.

        Returns:
            Current version number
        """
        return self._version

    def apply_mutations(self, mutations: List[StoreMutation]) -> None:
        """Apply normalized store mutations in one lock acquisition."""
        if not mutations:
            return

        with self.lock:
            self._version += 1
            for mutation in mutations:
                if isinstance(mutation, DamageMutation):
                    self._apply_damage_mutation_locked(mutation)
                elif isinstance(mutation, AttackMutation):
                    self._apply_attack_mutation_locked(mutation)
                elif isinstance(mutation, ImmunityMutation):
                    self._apply_immunity_mutation_locked(mutation)
                elif isinstance(mutation, SaveMutation):
                    self._apply_save_mutation_locked(mutation)
                elif isinstance(mutation, EpicDodgeMutation):
                    self._apply_epic_dodge_mutation_locked(mutation)

    def _add_target_locked(self, target: str) -> None:
        """Add a target to the cache and invalidate sorted order when needed."""
        if target and target not in self._targets_cache:
            self._targets_cache.add(target)
            self._sorted_targets_dirty = True

    def _get_sorted_targets_locked(self) -> tuple[str, ...]:
        """Return cached sorted targets while lock is held."""
        if self._sorted_targets_dirty:
            self._sorted_targets_cache = tuple(
                sorted(self._targets_cache, key=str.casefold)
            )
            self._sorted_targets_dirty = False
        return self._sorted_targets_cache

    def _update_dps_data_locked(
        self,
        character: str,
        damage_amount: int,
        timestamp: datetime,
        damage_types: Optional[Dict[str, int]] = None,
    ) -> None:
        """Update DPS data while lock is held."""
        if self.last_damage_timestamp is None or timestamp > self.last_damage_timestamp:
            self.last_damage_timestamp = timestamp
        if self._earliest_timestamp is None or timestamp < self._earliest_timestamp:
            self._earliest_timestamp = timestamp

        char_data = self.dps_data.get(character)
        if char_data is None:
            self.dps_data[character] = {
                'total_damage': damage_amount,
                'first_timestamp': timestamp,
                'damage_by_type': damage_types.copy() if damage_types else {}
            }
            self._dps_breakdown_dirty_characters.add(character)
            return

        char_data['total_damage'] += damage_amount
        if timestamp < char_data['first_timestamp']:
            char_data['first_timestamp'] = timestamp

        if not damage_types:
            return

        damage_by_type = char_data.get('damage_by_type')
        if damage_by_type is None:
            char_data['damage_by_type'] = damage_types.copy()
        else:
            for damage_type, amount in damage_types.items():
                amount_int = int(amount or 0)
                damage_by_type[damage_type] = damage_by_type.get(damage_type, 0) + amount_int
        self._dps_breakdown_dirty_characters.add(character)

    def _apply_damage_mutation_locked(self, mutation: DamageMutation) -> None:
        """Apply one normalized damage mutation while lock is held."""
        timestamp = mutation.timestamp
        if mutation.count_for_dps and not mutation.damage_type:
            if mutation.attacker:
                self._update_dps_data_locked(
                    mutation.attacker,
                    mutation.total_damage,
                    timestamp,
                    mutation.damage_types,
                )
            return

        event = DamageEvent(
            target=mutation.target,
            damage_type=mutation.damage_type,
            immunity_absorbed=mutation.immunity_absorbed,
            total_damage_dealt=mutation.total_damage,
            attacker=mutation.attacker,
            timestamp=timestamp,
        )
        self.events.append(event)
        self._all_damage_types_cache.add(mutation.damage_type)
        self._add_target_locked(mutation.target)
        if (
            mutation.target not in self._earliest_timestamp_by_target
            or timestamp < self._earliest_timestamp_by_target[mutation.target]
        ):
            self._earliest_timestamp_by_target[mutation.target] = timestamp
        self._damage_taken_by_target[mutation.target] = (
            self._damage_taken_by_target.get(mutation.target, 0) + mutation.total_damage
        )
        target_stats = self._target_stats_cache.setdefault(
            mutation.target, {'total_hits': 0, 'total_damage': 0, 'total_absorbed': 0}
        )
        target_stats['total_hits'] += 1
        target_stats['total_damage'] += mutation.total_damage
        target_stats['total_absorbed'] += mutation.immunity_absorbed

        if mutation.total_damage > 0 and mutation.attacker:
            self._damage_dealers_cache.add(mutation.attacker)
            dealers = self._damage_dealers_by_target.setdefault(mutation.target, set())
            dealers.add(mutation.attacker)

        if mutation.attacker:
            key = (mutation.attacker, mutation.target)
            summary = self._dps_by_attacker_target.get(key)
            if summary is None:
                self._dps_by_attacker_target[key] = {
                    'total_damage': mutation.total_damage,
                    'first_timestamp': timestamp,
                    'last_timestamp': timestamp,
                    'damage_by_type': {mutation.damage_type: mutation.total_damage},
                }
            else:
                summary['total_damage'] += mutation.total_damage
                if timestamp < summary['first_timestamp']:
                    summary['first_timestamp'] = timestamp
                if timestamp > summary['last_timestamp']:
                    summary['last_timestamp'] = timestamp
                damage_by_type = summary['damage_by_type']
                damage_by_type[mutation.damage_type] = (
                    damage_by_type.get(mutation.damage_type, 0) + mutation.total_damage
                )
            self._dps_breakdown_dirty_attacker_target.add(key)

        if mutation.target not in self._damage_summary_by_target:
            self._damage_summary_by_target[mutation.target] = {}
        if mutation.damage_type not in self._damage_summary_by_target[mutation.target]:
            self._damage_summary_by_target[mutation.target][mutation.damage_type] = {'max_damage': 0}
        damage_summary = self._damage_summary_by_target[mutation.target][mutation.damage_type]
        if mutation.total_damage > damage_summary['max_damage']:
            damage_summary['max_damage'] = mutation.total_damage

    def _apply_attack_mutation_locked(self, mutation: AttackMutation) -> None:
        """Apply one normalized attack mutation while lock is held."""
        event = AttackEvent(
            attacker=mutation.attacker,
            target=mutation.target,
            outcome=mutation.outcome,
            roll=mutation.roll,
            bonus=mutation.bonus,
            total=mutation.total,
        )
        self.attacks.append(event)
        key = (mutation.attacker, mutation.target)
        attacker_stats = self._attack_stats_by_attacker.setdefault(
            mutation.attacker, {'hits': 0, 'crits': 0, 'misses': 0}
        )
        target_stats = self._attack_stats_by_target.setdefault(
            mutation.target, {'hits': 0, 'crits': 0, 'misses': 0}
        )
        attacker_target_stats = self._attack_stats_by_attacker_target.setdefault(
            key, {'hits': 0, 'crits': 0, 'misses': 0}
        )
        if mutation.outcome == 'hit':
            attacker_stats['hits'] += 1
            target_stats['hits'] += 1
            attacker_target_stats['hits'] += 1
        elif mutation.outcome == 'critical_hit':
            attacker_stats['crits'] += 1
            target_stats['crits'] += 1
            attacker_target_stats['crits'] += 1
        elif mutation.outcome == 'miss':
            attacker_stats['misses'] += 1
            target_stats['misses'] += 1
            attacker_target_stats['misses'] += 1

        self._record_target_attack_roll_locked(
            attacker=mutation.attacker,
            target=mutation.target,
            outcome=mutation.outcome,
            bonus=mutation.bonus,
            total=mutation.total,
            was_nat1=mutation.was_nat1,
            was_nat20=mutation.was_nat20,
            is_concealment=mutation.is_concealment,
        )

    def _apply_immunity_mutation_locked(self, mutation: ImmunityMutation) -> None:
        """Apply one normalized immunity mutation while lock is held."""
        self._add_target_locked(mutation.target)
        if mutation.target not in self.immunity_data:
            self.immunity_data[mutation.target] = {}
        if mutation.damage_type not in self.immunity_data[mutation.target]:
            self.immunity_data[mutation.target][mutation.damage_type] = {
                'max_immunity': 0,
                'max_damage': 0,
                'sample_count': 0,
            }
        record = self.immunity_data[mutation.target][mutation.damage_type]
        record['sample_count'] += 1
        if (
            mutation.damage_dealt > record['max_damage']
            or (
                mutation.damage_dealt == record['max_damage']
                and mutation.immunity_points > record['max_immunity']
            )
        ):
            record['max_damage'] = mutation.damage_dealt
            record['max_immunity'] = mutation.immunity_points

    def _apply_save_mutation_locked(self, mutation: SaveMutation) -> None:
        """Apply one normalized save mutation while lock is held."""
        self._add_target_locked(mutation.target)
        saves = self._target_saves_by_name.get(mutation.target)
        if saves is None:
            saves = EnemySaves(name=mutation.target)
            self._target_saves_by_name[mutation.target] = saves
        saves.update_save(mutation.save_key, int(mutation.bonus))

    def _apply_epic_dodge_mutation_locked(self, mutation: EpicDodgeMutation) -> None:
        """Apply one normalized epic-dodge mutation while lock is held."""
        self._add_target_locked(mutation.target)
        ac = self._target_ac_by_name.get(mutation.target)
        if ac is None:
            ac = EnemyAC(name=mutation.target)
            self._target_ac_by_name[mutation.target] = ac
        ac.mark_epic_dodge()

    def _record_target_attack_roll_locked(
        self,
        *,
        attacker: str,
        target: str,
        outcome: str,
        bonus: Optional[int],
        total: Optional[int],
        was_nat1: bool,
        was_nat20: bool,
        is_concealment: bool,
    ) -> None:
        """Update target AC/AB indices from an attack while lock is held."""
        if target:
            self._add_target_locked(target)
        if target and total is not None and not is_concealment:
            ac = self._target_ac_by_name.get(target)
            if ac is None:
                ac = EnemyAC(name=target)
                self._target_ac_by_name[target] = ac
            if outcome in ('hit', 'critical_hit'):
                ac.record_hit(int(total), was_nat20=was_nat20)
            elif outcome == 'miss':
                ac.record_miss(int(total), was_nat1=was_nat1)

        if attacker and bonus is not None:
            tab = self._target_attack_bonus_by_name.get(attacker)
            if tab is None:
                tab = TargetAttackBonus(name=attacker)
                self._target_attack_bonus_by_name[attacker] = tab
            tab.record_bonus(int(bonus))

    def _get_character_breakdown_token(self, character: str, damage_by_type: Dict[str, int]) -> tuple[tuple[str, int], ...]:
        """Return cached sorted damage breakdown token for one character."""
        if (
            character not in self._dps_breakdown_token_by_character
            or character in self._dps_breakdown_dirty_characters
        ):
            token = tuple(sorted(damage_by_type.items()))
            self._dps_breakdown_token_by_character[character] = token
            self._dps_breakdown_dirty_characters.discard(character)
        return self._dps_breakdown_token_by_character[character]

    def _get_attacker_target_breakdown_token(
        self,
        key: Tuple[str, str],
        damage_by_type: Dict[str, int],
    ) -> tuple[tuple[str, int], ...]:
        """Return cached sorted damage breakdown token for one attacker/target pair."""
        if (
            key not in self._dps_breakdown_token_by_attacker_target
            or key in self._dps_breakdown_dirty_attacker_target
        ):
            token = tuple(sorted(damage_by_type.items()))
            self._dps_breakdown_token_by_attacker_target[key] = token
            self._dps_breakdown_dirty_attacker_target.discard(key)
        return self._dps_breakdown_token_by_attacker_target[key]

    def _build_dps_summaries_locked(
        self,
        *,
        target: Optional[str],
    ) -> tuple[DpsSummarySnapshot, ...]:
        """Build immutable DPS summaries while lock is held."""
        snapshots: list[DpsSummarySnapshot] = []
        if target is None:
            summaries = self.dps_data.items()
            for character, summary in summaries:
                damage_by_type = summary.get("damage_by_type", {})
                breakdown_token = self._get_character_breakdown_token(
                    str(character),
                    damage_by_type,
                )
                snapshots.append(
                    DpsSummarySnapshot(
                        character=str(character),
                        total_damage=int(summary["total_damage"]),
                        first_timestamp=summary["first_timestamp"],
                        last_timestamp=None,
                        damage_by_type=breakdown_token,
                        breakdown_token=breakdown_token,
                    )
                )
            return tuple(snapshots)

        attackers = self._damage_dealers_by_target.get(target, set())
        for attacker in attackers:
            summary = self._dps_by_attacker_target.get((attacker, target))
            if summary is None:
                continue
            damage_by_type = summary["damage_by_type"]
            breakdown_token = self._get_attacker_target_breakdown_token(
                (str(attacker), str(target)),
                damage_by_type,
            )
            snapshots.append(
                DpsSummarySnapshot(
                    character=str(attacker),
                    total_damage=int(summary["total_damage"]),
                    first_timestamp=summary["first_timestamp"],
                    last_timestamp=summary["last_timestamp"],
                    damage_by_type=breakdown_token,
                    breakdown_token=breakdown_token,
                )
            )
        return tuple(snapshots)

    def get_earliest_timestamp(self) -> Optional[datetime]:
        """Get the earliest timestamp from all recorded DPS data.

        Returns:
            The earliest timestamp of the first attack by any character, or None if no data
        """
        with self.lock:
            return self._earliest_timestamp

    def get_last_damage_timestamp(self) -> Optional[datetime]:
        """Get the latest timestamp from all recorded DPS data."""
        with self.lock:
            return self.last_damage_timestamp

    def get_dps_summaries(self) -> tuple[DpsSummarySnapshot, ...]:
        """Get immutable indexed DPS summaries for all characters."""
        with self.lock:
            return self._build_dps_summaries_locked(target=None)

    def get_target_dps_summaries(self, target: str) -> tuple[DpsSummarySnapshot, ...]:
        """Get immutable indexed DPS summaries for one target."""
        with self.lock:
            return self._build_dps_summaries_locked(target=target)

    def get_dps_projection_snapshot(
        self,
        target: str | None = None,
    ) -> DpsProjectionSnapshot:
        """Get one atomic DPS projection snapshot for query consumption."""
        with self.lock:
            earliest_timestamp = (
                self._earliest_timestamp
                if target is None
                else self._earliest_timestamp_by_target.get(target)
            )
            return DpsProjectionSnapshot(
                last_damage_timestamp=self.last_damage_timestamp,
                earliest_timestamp=earliest_timestamp,
                summaries=self._build_dps_summaries_locked(target=target),
            )

    def get_target_damage_type_snapshots(
        self,
        target: str,
    ) -> tuple[TargetDamageTypeSnapshot, ...]:
        """Get immutable indexed damage/immunity snapshots for one target."""
        with self.lock:
            damage_summary = self._damage_summary_by_target.get(target, {})
            immunity_summary = self.immunity_data.get(target, {})
            damage_types = sorted(set(damage_summary) | set(immunity_summary))
            return tuple(
                TargetDamageTypeSnapshot(
                    damage_type=damage_type,
                    max_event_damage=int(
                        damage_summary.get(damage_type, {}).get("max_damage", 0)
                    ),
                    max_immunity_damage=int(
                        immunity_summary.get(damage_type, {}).get("max_damage", 0)
                    ),
                    immunity_absorbed=int(
                        immunity_summary.get(damage_type, {}).get("max_immunity", 0)
                    ),
                    sample_count=int(
                        immunity_summary.get(damage_type, {}).get("sample_count", 0)
                    ),
                )
                for damage_type in damage_types
            )

    def get_all_target_summary_snapshots(self) -> tuple[TargetSummarySnapshot, ...]:
        """Get immutable indexed summary snapshots for all known targets."""
        with self.lock:
            rows: list[TargetSummarySnapshot] = []
            for target in self._get_sorted_targets_locked():
                ab_display = "-"
                attack_bonus = self._target_attack_bonus_by_name.get(target)
                if attack_bonus is not None:
                    ab_display = attack_bonus.get_bonus_display()

                ac_display = "-"
                ac = self._target_ac_by_name.get(target)
                if ac is not None:
                    ac_display = ac.get_ac_estimate()

                saves = self._target_saves_by_name.get(target)
                rows.append(
                    TargetSummarySnapshot(
                        target=target,
                        ab_display=ab_display,
                        ac_display=ac_display,
                        fortitude=None if saves is None else saves.fortitude,
                        reflex=None if saves is None else saves.reflex,
                        will=None if saves is None else saves.will,
                        damage_taken=int(self._damage_taken_by_target.get(target, 0)),
                    )
                )
            return tuple(rows)

    def get_target_resists(self, target: str) -> List[Tuple[str, int, int, int]]:
        """Get aggregated resist data for a specific target.

        This uses the separate immunity_data tracking to get accurate immunity absorbed values
        along with the coupled max_damage value from the same hit.

        Args:
            target: Name of the target to query

        Returns:
            List of tuples (damage_type, max_damage, immunity_absorbed, sample_count)
            where max_damage and immunity_absorbed are from the same hit that dealt the most damage
        """
        with self.lock:
            if target not in self.immunity_data:
                return []

            result = []
            for damage_type, immunity_info in self.immunity_data[target].items():
                result.append((
                    damage_type,
                    immunity_info['max_damage'],
                    immunity_info['max_immunity'],
                    immunity_info['sample_count'],
                ))

            # Sort by damage type
            result.sort(key=lambda x: x[0])
            return result

    def get_all_targets(self) -> List[str]:
        """Get list of all unique targets.

        Returns:
            Sorted list of target names
        """
        with self.lock:
            return list(self._get_sorted_targets_locked())

    def get_target_stats(self, target: str) -> Optional[Tuple[int, int, int]]:
        """Get overall stats for a target.

        Args:
            target: Name of the target

        Returns:
            Tuple of (total_hits, total_damage, total_absorbed) or None
        """
        with self.lock:
            stats = self._target_stats_cache.get(target)
            if stats is None or stats['total_hits'] == 0:
                return None
            return (
                int(stats['total_hits']),
                int(stats['total_damage']),
                int(stats['total_absorbed']),
            )

    def get_attack_stats(self, attacker: str, target: str) -> Optional[dict]:
        """Get attack statistics for a specific attacker vs target.

        Args:
            attacker: Name of the attacker
            target: Name of the target

        Returns:
            Dict with keys 'attacks', 'hits', 'crits', 'misses', 'hit_rate' or None
        """
        with self.lock:
            stats = self._attack_stats_by_attacker_target.get((attacker, target))
            if not stats:
                return None

            hits = int(stats['hits'])
            crits = int(stats['crits'])
            misses = int(stats['misses'])
            total_attacks = hits + crits + misses

            # Calculate hit rate as (hits + crits) / (hits + crits + misses)
            successful = hits + crits
            attempted = successful + misses
            hit_rate = (successful / attempted * 100) if attempted > 0 else 0.0

            return {
                'total_attacks': total_attacks,
                'hits': hits,
                'crits': crits,
                'misses': misses,
                'successful': successful,
                'hit_rate': hit_rate
            }

    def get_attack_stats_for_target(self, target: str) -> Optional[dict]:
        """Get combined attack statistics against a target from all attackers.

        Args:
            target: Name of the target

        Returns:
            Dict with keys 'attacks', 'hits', 'crits', 'misses', 'hit_rate' or None
        """
        with self.lock:
            stats = self._attack_stats_by_target.get(target)
            if not stats:
                return None

            hits = int(stats['hits'])
            crits = int(stats['crits'])
            misses = int(stats['misses'])
            total_attacks = hits + crits + misses

            # Calculate hit rate as (hits + crits) / (hits + crits + misses)
            successful = hits + crits
            attempted = successful + misses
            hit_rate = (successful / attempted * 100) if attempted > 0 else 0.0

            return {
                'total_attacks': total_attacks,
                'hits': hits,
                'crits': crits,
                'misses': misses,
                'successful': successful,
                'hit_rate': hit_rate
            }

    def get_hit_rate_per_character(self, target: Optional[str] = None) -> Dict[str, float]:
        """Get overall hit rate percentage for each character.

        Args:
            target: Optional target to filter by. If None, returns hit rate for all targets.

        Returns:
            Dict mapping character name to hit rate percentage (0-100)
        """
        with self.lock:
            # Use single-pass aggregation for better performance
            # attacker -> {'hits': count, 'crits': count, 'misses': count}
            if target is None:
                stats_by_attacker = self._attack_stats_by_attacker
            else:
                stats_by_attacker = {
                    attacker: stats
                    for (attacker, attack_target), stats in self._attack_stats_by_attacker_target.items()
                    if attack_target == target
                }

            # Calculate hit rates from aggregated stats
            character_hit_rates: Dict[str, float] = {}
            for attacker, stats in stats_by_attacker.items():
                successful = stats['hits'] + stats['crits']
                attempted = successful + stats['misses']
                hit_rate = (successful / attempted * 100) if attempted > 0 else 0.0
                character_hit_rates[attacker] = hit_rate

            return character_hit_rates

    def get_hit_rate_for_damage_dealers(self, target: Optional[str] = None) -> Dict[str, float]:
        """Get hit rate for only the characters who dealt damage (from damage events).

        This method ensures that hit rates are calculated only for characters
        who appear in the DPS list, preventing mismatches between DPS and hit rate data.

        Args:
            target: Optional target to filter by. If None, returns hit rate for all targets.

        Returns:
            Dict mapping character name to hit rate percentage (0-100)
        """
        with self.lock:
            # Determine which characters dealt damage using cached set when possible
            if target:
                damage_dealers = self._damage_dealers_by_target.get(target, set())
            else:
                # Use cached damage dealers set
                damage_dealers = self._damage_dealers_cache

            if not damage_dealers:
                return {}

            # Use indexed attacks when filtering by target
            if target:
                stats_by_attacker = {
                    attacker: self._attack_stats_by_attacker_target.get(
                        (attacker, target), {'hits': 0, 'crits': 0, 'misses': 0}
                    )
                    for attacker in damage_dealers
                }
            else:
                stats_by_attacker = {
                    attacker: self._attack_stats_by_attacker.get(
                        attacker, {'hits': 0, 'crits': 0, 'misses': 0}
                    )
                    for attacker in damage_dealers
                }

            # Calculate hit rates from aggregated stats
            character_hit_rates: Dict[str, float] = {}
            for attacker, stats in stats_by_attacker.items():
                successful = stats['hits'] + stats['crits']
                attempted = successful + stats['misses']
                hit_rate = (successful / attempted * 100) if attempted > 0 else 0.0
                character_hit_rates[attacker] = hit_rate
            return character_hit_rates

    def get_earliest_timestamp_for_target(self, target: str) -> Optional[datetime]:
        """Get the earliest attack timestamp for a specific target.

        Args:
            target: Target to query

        Returns:
            Earliest timestamp for attacks on this target, or None if no attacks
        """
        with self.lock:
            return self._earliest_timestamp_by_target.get(target)

    def record_target_attack_roll(
        self,
        attacker: str,
        target: str,
        outcome: str,
        roll: Optional[int],
        bonus: Optional[int],
        total: Optional[int],
        was_nat1: bool = False,
        was_nat20: bool = False,
        is_concealment: bool = False,
    ) -> None:
        """Record attack-derived AC/AB target stats.

        Args:
            attacker: Name of the attacking character
            target: Name of the target
            outcome: Attack outcome ('hit', 'critical_hit', or 'miss')
            roll: d20 roll value
            bonus: Attack bonus value
            total: Attack total (roll + bonus)
            was_nat1: Whether the attack roll was a natural 1
            was_nat20: Whether the attack roll was a natural 20
            is_concealment: Whether this miss was concealment-based
        """
        with self.lock:
            self._version += 1
            self._record_target_attack_roll_locked(
                attacker=attacker,
                target=target,
                outcome=outcome,
                bonus=bonus,
                total=total,
                was_nat1=was_nat1,
                was_nat20=was_nat20,
                is_concealment=is_concealment,
            )

    def clear_all_data(self) -> None:
        """Clear all data from the store."""
        with self.lock:
            self._version += 1
            self.events.clear()
            self.attacks.clear()
            self.dps_data.clear()
            self.immunity_data.clear()
            self.last_damage_timestamp = None
            self._earliest_timestamp = None
            self._earliest_timestamp_by_target.clear()
            # Clear caches
            self._targets_cache.clear()
            self._damage_dealers_cache.clear()
            self._all_damage_types_cache.clear()
            self._sorted_targets_cache = ()
            self._sorted_targets_dirty = False
            self._damage_taken_by_target.clear()
            self._attack_stats_by_attacker.clear()
            self._attack_stats_by_target.clear()
            self._attack_stats_by_attacker_target.clear()
            self._damage_summary_by_target.clear()
            self._damage_dealers_by_target.clear()
            self._dps_by_attacker_target.clear()
            self._dps_breakdown_token_by_character.clear()
            self._dps_breakdown_dirty_characters.clear()
            self._dps_breakdown_token_by_attacker_target.clear()
            self._dps_breakdown_dirty_attacker_target.clear()
            self._target_stats_cache.clear()
            self._target_ac_by_name.clear()
            self._target_saves_by_name.clear()
            self._target_attack_bonus_by_name.clear()

    def close(self) -> None:
        """Close the data store (no-op for in-memory store)."""
        pass

    def get_all_damage_types(self) -> List[str]:
        """Return a sorted list of all damage types seen in the store.

        Returns:
            Sorted list of damage type names
        """
        with self.lock:
            return sorted(self._all_damage_types_cache)

    def get_max_damage_for_target_and_type(self, target: str, damage_type: str) -> int:
        """Return the maximum single-hit damage recorded for target+damage_type.

        Args:
            target: Name of the target
            damage_type: Type of damage

        Returns:
            Maximum damage amount recorded for this combination
        """
        with self.lock:
            if target in self.immunity_data and damage_type in self.immunity_data[target]:
                return self.immunity_data[target][damage_type]['max_damage']
            return 0

    def get_max_damage_from_events_for_target_and_type(self, target: str, damage_type: str) -> int:
        """Return the maximum single-hit damage from events for target+damage_type.

        This method looks directly at damage events, not immunity_data, so it can
        find max damage even for damage types with no immunity records.

        Args:
            target: Name of the target
            damage_type: Type of damage

        Returns:
            Maximum damage amount recorded for this combination, or 0 if no events
        """
        with self.lock:
            damage_summary = self._damage_summary_by_target.get(target, {}).get(damage_type)
            if damage_summary is None:
                return 0
            return damage_summary['max_damage']

    def get_immunity_for_target_and_type(self, target: str, damage_type: str) -> Dict[str, int]:
        """Get immunity data for a specific target and damage type.

        Args:
            target: Name of the target
            damage_type: Type of damage

        Returns:
            Dictionary with keys: max_immunity, max_damage, sample_count
        """
        with self.lock:
            if target in self.immunity_data and damage_type in self.immunity_data[target]:
                return self.immunity_data[target][damage_type].copy()
            return {'max_immunity': 0, 'max_damage': 0, 'sample_count': 0}

