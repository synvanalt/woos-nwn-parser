"""In-memory data storage for Woo's NWN Parser.

This module provides the DataStore class that manages all application data
using Python dataclasses instead of a database, providing session-only storage.
"""

import threading
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

from .models import AttackEvent, DamageEvent, EnemyAC, EnemySaves, TargetAttackBonus


class DataStore:
    """In-memory data store using dataclasses.

    Provides the same interface as the old Database class for easy migration.
    All data is stored in memory and lost when the app closes (session-only).
    """

    def __init__(
        self,
        max_events_history: int = 200000,
        max_attacks_history: int = 200000,
    ) -> None:
        """Initialize the data store."""
        self.max_events_history = max(1, int(max_events_history))
        self.max_attacks_history = max(1, int(max_attacks_history))
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
        self._all_damage_types_cache: set[str] = set()
        self._target_stats_cache: Dict[str, Dict[str, int]] = {}
        self._target_ac_by_name: Dict[str, EnemyAC] = {}
        self._target_saves_by_name: Dict[str, EnemySaves] = {}
        self._target_attack_bonus_by_name: Dict[str, TargetAttackBonus] = {}

    @property
    def version(self) -> int:
        """Get the current data version for change detection.

        This version is incremented on every data modification, allowing
        callers to efficiently detect when data has changed.

        Returns:
            Current version number
        """
        return self._version

    def insert_attack_event(self, attacker: str, target: str, outcome: str, roll: Optional[int] = None,
                           bonus: Optional[int] = None, total: Optional[int] = None,
                           was_nat1: bool = False, was_nat20: bool = False,
                           is_concealment: bool = False) -> None:
        """Insert an attack event into the in-memory store.

        Args:
            attacker: Name of the attacking character
            target: Name of the target
            outcome: Outcome of the attack ('hit', 'miss', 'critical_hit')
            roll: The d20 roll value
            bonus: Attack bonus
            total: Total attack roll (roll + bonus)
            was_nat1: Whether this was a natural 1
            was_nat20: Whether this was a natural 20
            is_concealment: Whether this miss was concealment-based
        """
        with self.lock:
            self._version += 1
            event = AttackEvent(
                attacker=attacker,
                target=target,
                outcome=outcome,
                roll=roll,
                bonus=bonus,
                total=total
            )
            self.attacks.append(event)
            key = (attacker, target)
            if attacker not in self._attack_stats_by_attacker:
                self._attack_stats_by_attacker[attacker] = {'hits': 0, 'crits': 0, 'misses': 0}

            attacker_stats = self._attack_stats_by_attacker[attacker]
            target_stats = self._attack_stats_by_target.setdefault(
                target, {'hits': 0, 'crits': 0, 'misses': 0}
            )
            attacker_target_stats = self._attack_stats_by_attacker_target.setdefault(
                key, {'hits': 0, 'crits': 0, 'misses': 0}
            )
            if outcome == 'hit':
                attacker_stats['hits'] += 1
                target_stats['hits'] += 1
                attacker_target_stats['hits'] += 1
            elif outcome == 'critical_hit':
                attacker_stats['crits'] += 1
                target_stats['crits'] += 1
                attacker_target_stats['crits'] += 1
            elif outcome == 'miss':
                attacker_stats['misses'] += 1
                target_stats['misses'] += 1
                attacker_target_stats['misses'] += 1

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
            self._targets_cache.add(target)

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

    def insert_damage_event(self, target: str, damage_type: str, immunity: int, total_damage: int, attacker: str = "", timestamp: Optional[datetime] = None) -> None:
        """Insert a damage event into the in-memory store.

        Args:
            target: Name of the target
            damage_type: Type of damage (e.g., 'Fire', 'Physical')
            immunity: Amount of damage absorbed by immunity
            total_damage: Total damage dealt
            attacker: Name of the character who dealt the damage
            timestamp: Timestamp when the damage occurred (defaults to now if not provided)
        """
        with self.lock:
            self._version += 1
            if timestamp is None:
                timestamp = datetime.now()
            event = DamageEvent(
                target=target,
                damage_type=damage_type,
                immunity_absorbed=immunity,
                total_damage_dealt=total_damage,
                attacker=attacker,
                timestamp=timestamp
            )
            self.events.append(event)
            self._all_damage_types_cache.add(damage_type)
            # Update targets cache (O(1) set add)
            self._targets_cache.add(target)
            self._damage_taken_by_target[target] = (
                self._damage_taken_by_target.get(target, 0) + total_damage
            )
            target_stats = self._target_stats_cache.setdefault(
                target, {'total_hits': 0, 'total_damage': 0, 'total_absorbed': 0}
            )
            target_stats['total_hits'] += 1
            target_stats['total_damage'] += total_damage
            target_stats['total_absorbed'] += immunity
            # Update damage dealers cache if damage was dealt
            if total_damage > 0 and attacker:
                self._damage_dealers_cache.add(attacker)
                if target not in self._damage_dealers_by_target:
                    self._damage_dealers_by_target[target] = set()
                self._damage_dealers_by_target[target].add(attacker)

            if attacker:
                key = (attacker, target)
                summary = self._dps_by_attacker_target.get(key)
                if summary is None:
                    self._dps_by_attacker_target[key] = {
                        'total_damage': total_damage,
                        'first_timestamp': timestamp,
                        'last_timestamp': timestamp,
                        'damage_by_type': {damage_type: total_damage},
                    }
                else:
                    summary['total_damage'] += total_damage
                    if timestamp < summary['first_timestamp']:
                        summary['first_timestamp'] = timestamp
                    if timestamp > summary['last_timestamp']:
                        summary['last_timestamp'] = timestamp
                    damage_by_type = summary['damage_by_type']
                    damage_by_type[damage_type] = damage_by_type.get(damage_type, 0) + total_damage
                self._dps_breakdown_dirty_attacker_target.add(key)

            if target not in self._damage_summary_by_target:
                self._damage_summary_by_target[target] = {}

            if damage_type not in self._damage_summary_by_target[target]:
                self._damage_summary_by_target[target][damage_type] = {'max_damage': 0}

            damage_summary = self._damage_summary_by_target[target][damage_type]
            if total_damage > damage_summary['max_damage']:
                damage_summary['max_damage'] = total_damage

    def update_dps_data(self, character: str, damage_amount: int, timestamp: datetime, damage_types: Optional[Dict[str, int]] = None) -> None:
        """Update DPS data for a character.

        Args:
            character: Character name dealing the damage
            damage_amount: Amount of damage dealt
            timestamp: Timestamp when the damage was dealt
            damage_types: Dictionary mapping damage type to amount for this hit
        """
        with self.lock:
            self._version += 1
            # Always update the global last damage timestamp
            if self.last_damage_timestamp is None or timestamp > self.last_damage_timestamp:
                self.last_damage_timestamp = timestamp
            if self._earliest_timestamp is None or timestamp < self._earliest_timestamp:
                self._earliest_timestamp = timestamp

            char_data = self.dps_data.get(character)
            if char_data is None:
                # New character - initialize everything at once
                self.dps_data[character] = {
                    'total_damage': damage_amount,
                    'first_timestamp': timestamp,
                    'damage_by_type': damage_types.copy() if damage_types else {}
                }
                self._dps_breakdown_dirty_characters.add(character)
            else:
                # Existing character - update efficiently
                char_data['total_damage'] += damage_amount
                # Update first timestamp if this one is older
                if timestamp < char_data['first_timestamp']:
                    char_data['first_timestamp'] = timestamp

                # Track damage by type if provided
                if damage_types:
                    damage_by_type = char_data.get('damage_by_type')
                    if damage_by_type is None:
                        char_data['damage_by_type'] = damage_types.copy()
                    else:
                        # Batch update damage types
                        for damage_type, amount in damage_types.items():
                            amount_int = int(amount or 0)
                            if damage_type in damage_by_type:
                                damage_by_type[damage_type] += amount_int
                            else:
                                damage_by_type[damage_type] = amount_int
                        self._dps_breakdown_dirty_characters.add(character)

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

    def get_earliest_timestamp(self) -> Optional[datetime]:
        """Get the earliest timestamp from all recorded DPS data.

        Returns:
            The earliest timestamp of the first attack by any character, or None if no data
        """
        with self.lock:
            return self._earliest_timestamp

    def get_dps_data(self, time_tracking_mode: str = "per_character", global_start_time: Optional[datetime] = None) -> List[Dict]:
        """Get DPS data for all characters, sorted by DPS descending.

        Args:
            time_tracking_mode: Either "per_character" or "global"
            global_start_time: Start time for global mode (only used if time_tracking_mode is "global")

        Returns:
            List of dicts with keys: character, total_damage, time_seconds, dps
        """
        with self.lock:
            dps_list = []

            # If no damage recorded yet, return empty list
            if not self.dps_data:
                return dps_list

            if time_tracking_mode == "global":
                # Global mode: use global start time and global last damage timestamp
                if global_start_time is None:
                    # If global_start_time not set, fall back to first character's first timestamp
                    if not self.dps_data:
                        return dps_list
                    global_start_time = min(data['first_timestamp'] for data in self.dps_data.values())

                # Use the global last damage timestamp (same as per_character mode)
                if self.last_damage_timestamp is None:
                    return dps_list

                for character, data in self.dps_data.items():
                    total_damage = data['total_damage']
                    time_delta = self.last_damage_timestamp - global_start_time
                    time_seconds = max(time_delta.total_seconds(), 1)  # Avoid division by zero

                    # Calculate DPS
                    dps = total_damage / time_seconds

                    dps_list.append({
                        'character': character,
                        'total_damage': total_damage,
                        'time_seconds': time_delta,
                        'dps': dps,
                        'breakdown_token': self._get_character_breakdown_token(
                            character,
                            data.get('damage_by_type', {}),
                        ),
                    })
            else:
                # Per-character mode (default): use each character's own first timestamp (last timestamp is global)
                if self.last_damage_timestamp is None:
                    return dps_list

                for character, data in self.dps_data.items():
                    total_damage = data['total_damage']
                    first_ts = data['first_timestamp']
                    # Use the GLOBAL last damage timestamp, not individual character's
                    last_ts = self.last_damage_timestamp

                    # Calculate time elapsed in seconds
                    time_delta = last_ts - first_ts
                    time_seconds = max(time_delta.total_seconds(), 1)  # Avoid division by zero

                    # Calculate DPS
                    dps = total_damage / time_seconds

                    dps_list.append({
                        'character': character,
                        'total_damage': total_damage,
                        'time_seconds': time_delta,
                        'dps': dps,
                        'breakdown_token': self._get_character_breakdown_token(
                            character,
                            data.get('damage_by_type', {}),
                        ),
                    })

            # Sort by DPS descending
            dps_list.sort(key=lambda x: x['dps'], reverse=True)
            return dps_list

    def get_dps_breakdown_by_type(self, character: str, time_tracking_mode: str = "per_character", global_start_time: Optional[datetime] = None) -> List[Dict]:
        """Get DPS breakdown by damage type for a specific character.

        Args:
            character: Character name to get breakdown for
            time_tracking_mode: Either "per_character" or "global"
            global_start_time: Start time for global mode (only used if time_tracking_mode is "global")

        Returns:
            List of dicts with keys: damage_type, total_damage, dps
        """
        return self.get_dps_breakdowns_by_type(
            [character],
            target=None,
            time_tracking_mode=time_tracking_mode,
            global_start_time=global_start_time,
        ).get(character, [])

    def get_dps_breakdown_by_type_for_target(self, character: str, target: str, time_tracking_mode: str = "per_character", global_start_time: Optional[datetime] = None) -> List[Dict]:
        """Get DPS breakdown by damage type for a specific character against a specific target.

        Args:
            character: Character name to get breakdown for
            target: Target name to filter by
            time_tracking_mode: Either "per_character" or "global"
            global_start_time: Start time for global mode

        Returns:
            List of dicts with keys: damage_type, total_damage, dps
        """
        return self.get_dps_breakdowns_by_type(
            [character],
            target=target,
            time_tracking_mode=time_tracking_mode,
            global_start_time=global_start_time,
        ).get(character, [])

    def _build_dps_breakdown_rows(
        self,
        damage_by_type: Dict[str, int],
        time_seconds: float,
    ) -> List[Dict]:
        """Build sorted breakdown rows for one damage map."""
        breakdown = []
        for damage_type, total_dmg in damage_by_type.items():
            breakdown.append({
                'damage_type': damage_type,
                'total_damage': total_dmg,
                'dps': total_dmg / time_seconds,
            })

        breakdown.sort(key=lambda x: x['total_damage'], reverse=True)
        return breakdown

    def get_dps_breakdowns_by_type(
        self,
        characters: List[str],
        target: Optional[str] = None,
        time_tracking_mode: str = "per_character",
        global_start_time: Optional[datetime] = None,
    ) -> Dict[str, List[Dict]]:
        """Get DPS breakdowns by damage type for multiple characters in one lock pass."""
        with self.lock:
            unique_characters = list(dict.fromkeys(characters))
            result: Dict[str, List[Dict]] = {character: [] for character in unique_characters}
            if not unique_characters:
                return result

            global_time_seconds: Optional[float] = None
            if time_tracking_mode == "global":
                if global_start_time is None:
                    if not self.dps_data:
                        if target is None:
                            return result
                        global_start_time = datetime.now()
                    else:
                        global_start_time = min(
                            data['first_timestamp'] for data in self.dps_data.values()
                        )

                if self.last_damage_timestamp is None:
                    return result

                global_time_seconds = max(
                    (self.last_damage_timestamp - global_start_time).total_seconds(),
                    1,
                )

            for character in unique_characters:
                if target is None:
                    character_data = self.dps_data.get(character)
                    if character_data is None:
                        continue

                    if time_tracking_mode == "global":
                        time_seconds = global_time_seconds
                    else:
                        if self.last_damage_timestamp is None:
                            continue
                        time_seconds = max(
                            (self.last_damage_timestamp - character_data['first_timestamp']).total_seconds(),
                            1,
                        )

                    result[character] = self._build_dps_breakdown_rows(
                        character_data.get('damage_by_type', {}),
                        time_seconds or 1,
                    )
                    continue

                summary = self._dps_by_attacker_target.get((character, target))
                if summary is None or summary['total_damage'] == 0:
                    continue

                if time_tracking_mode == "global":
                    time_seconds = global_time_seconds
                else:
                    time_seconds = max(
                        (summary['last_timestamp'] - summary['first_timestamp']).total_seconds(),
                        1,
                    )

                result[character] = self._build_dps_breakdown_rows(
                    summary['damage_by_type'],
                    time_seconds or 1,
                )

            return result

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
            # Use cached set for O(1) lookup instead of O(n) iteration
            return sorted(self._targets_cache)

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

    def get_dps_data_for_target(self, target: str, time_tracking_mode: str = "per_character", global_start_time: Optional[datetime] = None) -> List[Dict]:
        """Get DPS data for all characters against a specific target.

        Args:
            target: Target to filter by
            time_tracking_mode: Either "per_character" or "global"
            global_start_time: Start time for global mode (only used if time_tracking_mode is "global")

        Returns:
            List of dicts with keys: character, total_damage, time_seconds, dps
        """
        with self.lock:
            dps_list = []

            attackers = self._damage_dealers_by_target.get(target, set())
            if not attackers:
                return dps_list

            if time_tracking_mode == "global":
                # Global mode: use global start time and global last damage timestamp
                if global_start_time is None:
                    first_timestamps = [
                        self._dps_by_attacker_target[(character, target)]['first_timestamp']
                        for character in attackers
                        if (character, target) in self._dps_by_attacker_target
                    ]
                    if not first_timestamps:
                        return dps_list
                    global_start_time = min(first_timestamps)

                # Use the global last damage timestamp (same as per_character mode)
                if self.last_damage_timestamp is None:
                    return dps_list

                for character in attackers:
                    summary = self._dps_by_attacker_target.get((character, target))
                    if summary is None or summary['total_damage'] == 0:
                        continue

                    time_delta = self.last_damage_timestamp - global_start_time
                    time_seconds = max(time_delta.total_seconds(), 1)
                    dps = summary['total_damage'] / time_seconds

                    dps_list.append({
                        'character': character,
                        'total_damage': summary['total_damage'],
                        'time_seconds': time_delta,
                        'dps': dps,
                        'breakdown_token': self._get_attacker_target_breakdown_token(
                            (character, target),
                            summary['damage_by_type'],
                        ),
                    })
            else:
                # Per-character mode: use each character's first and last damage on this target
                for character in attackers:
                    summary = self._dps_by_attacker_target.get((character, target))
                    if summary is None:
                        continue

                    if summary['total_damage'] == 0:
                        continue

                    time_delta = summary['last_timestamp'] - summary['first_timestamp']
                    time_seconds = max(time_delta.total_seconds(), 1)
                    dps = summary['total_damage'] / time_seconds

                    dps_list.append({
                        'character': character,
                        'total_damage': summary['total_damage'],
                        'time_seconds': time_delta,
                        'dps': dps,
                        'breakdown_token': self._get_attacker_target_breakdown_token(
                            (character, target),
                            summary['damage_by_type'],
                        ),
                    })

            # Sort by DPS descending
            dps_list.sort(key=lambda x: x['dps'], reverse=True)
            return dps_list

    def get_earliest_timestamp_for_target(self, target: str) -> Optional[datetime]:
        """Get the earliest attack timestamp for a specific target.

        Args:
            target: Target to query

        Returns:
            Earliest timestamp for attacks on this target, or None if no attacks
        """
        with self.lock:
            first_timestamps = [
                summary['first_timestamp']
                for (attacker, attack_target), summary in self._dps_by_attacker_target.items()
                if attack_target == target
            ]
            if not first_timestamps:
                return None

            return min(first_timestamps)

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

    def record_target_save(self, target: str, save_key: str, bonus: int) -> None:
        """Record save-derived target stats."""
        with self.lock:
            self._version += 1
            self._targets_cache.add(target)
            saves = self._target_saves_by_name.get(target)
            if saves is None:
                saves = EnemySaves(name=target)
                self._target_saves_by_name[target] = saves
            saves.update_save(save_key, int(bonus))

    def mark_target_epic_dodge(self, target: str) -> None:
        """Mark a target as having Epic Dodge for AC display confidence."""
        with self.lock:
            self._version += 1
            self._targets_cache.add(target)
            ac = self._target_ac_by_name.get(target)
            if ac is None:
                ac = EnemyAC(name=target)
                self._target_ac_by_name[target] = ac
            ac.mark_epic_dodge()


    def clear_all_data(self) -> None:
        """Clear all data from the store."""
        with self.lock:
            self.events.clear()
            self.attacks.clear()
            self.dps_data.clear()
            self.immunity_data.clear()
            self.last_damage_timestamp = None
            self._earliest_timestamp = None
            # Clear caches
            self._targets_cache.clear()
            self._damage_dealers_cache.clear()
            self._all_damage_types_cache.clear()
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

    def get_target_damage_type_summary(self, target: str) -> List[Dict[str, int | str]]:
        """Get one summary row per damage type seen for a target."""
        with self.lock:
            damage_summary = self._damage_summary_by_target.get(target, {})
            immunity_summary = self.immunity_data.get(target, {})

            if not damage_summary and not immunity_summary:
                return []

            result: List[Dict[str, int | str]] = []
            for damage_type in sorted(set(damage_summary) | set(immunity_summary)):
                damage_info = damage_summary.get(damage_type, {})
                immunity_info = immunity_summary.get(damage_type, {})
                result.append({
                    'damage_type': damage_type,
                    'max_event_damage': int(damage_info.get('max_damage', 0)),
                    'max_immunity_damage': int(immunity_info.get('max_damage', 0)),
                    'immunity_absorbed': int(immunity_info.get('max_immunity', 0)),
                    'sample_count': int(immunity_info.get('sample_count', 0)),
                })

            return result

    def get_all_targets_summary(self, parser: object = None) -> List[Dict]:
        """Get summary data for all targets with attack bonus, AC, and saves.

        Returns:
            List of dicts with keys: target, ab, ac, fortitude, reflex, will, damage_taken,
            Sorted alphabetically by target name
        """
        with self.lock:
            targets = sorted(self._targets_cache)
            summary = []

            for target in targets:
                # Get AB from DataStore-owned attack bonus state
                ab_display = "-"
                if target in self._target_attack_bonus_by_name:
                    ab_display = self._target_attack_bonus_by_name[target].get_bonus_display()

                # Get AC from DataStore-owned AC estimation state
                ac_display = "-"
                if target in self._target_ac_by_name:
                    ac_display = self._target_ac_by_name[target].get_ac_estimate()

                # Get saves from DataStore-owned save estimation state
                fort_display = "-"
                ref_display = "-"
                will_display = "-"
                if target in self._target_saves_by_name:
                    saves = self._target_saves_by_name[target]
                    fort_display = str(saves.fortitude) if saves.fortitude is not None else "-"
                    ref_display = str(saves.reflex) if saves.reflex is not None else "-"
                    will_display = str(saves.will) if saves.will is not None else "-"

                # Calculate total damage taken by this target
                damage_taken = self._damage_taken_by_target.get(target, 0)

                summary.append({
                    'target': target,
                    'ab': ab_display,
                    'ac': ac_display,
                    'fortitude': fort_display,
                    'reflex': ref_display,
                    'will': will_display,
                    'damage_taken': str(damage_taken)
                })

            return summary

    def record_immunity(self, target: str, damage_type: str, immunity_points: int, damage_dealt: int) -> None:
        """Record immunity data for a target and damage type.

        This tracks damage and associated immunity as a coupled pair from the same hit.
        Only updates when a new higher damage is recorded, ensuring the immunity value
        shown corresponds to the hit that dealt the most damage (not tracked independently).

        This is important because enemies can have temporary 100% immunity buffs, which
        would skew the immunity percentage calculation if tracked independently.

        Args:
            target: Name of the target
            damage_type: Type of damage
            immunity_points: Amount of damage absorbed by immunity for this specific hit
            damage_dealt: Amount of damage dealt for this specific hit
        """
        with self.lock:
            if target not in self.immunity_data:
                self.immunity_data[target] = {}

            if damage_type not in self.immunity_data[target]:
                self.immunity_data[target][damage_type] = {
                    'max_immunity': 0,
                    'max_damage': 0,
                    'sample_count': 0
                }

            record = self.immunity_data[target][damage_type]
            record['sample_count'] += 1

            # Only update max_damage AND associated max_immunity together when this hit
            # deals more damage than the previous maximum. This ensures the immunity value
            # shown is from the same hit as the max damage, not tracked independently.
            if damage_dealt > record['max_damage']:
                record['max_damage'] = damage_dealt
                record['max_immunity'] = immunity_points

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

