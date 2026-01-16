"""In-memory data storage for Woo's NWN Parser.

This module provides the DataStore class that manages all application data
using Python dataclasses instead of a database, providing session-only storage.
"""

import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .models import AttackEvent, DamageEvent


class DataStore:
    """In-memory data store using dataclasses.

    Provides the same interface as the old Database class for easy migration.
    All data is stored in memory and lost when the app closes (session-only).
    """

    def __init__(self) -> None:
        """Initialize the data store."""
        self.events: List[DamageEvent] = []
        self.attacks: List[AttackEvent] = []
        self.lock = threading.RLock()
        # DPS tracking: character_name -> {'damage': total, 'first_timestamp': datetime, 'last_timestamp': datetime, 'damage_by_type': {type: amount}}
        self.dps_data: Dict[str, Dict] = {}
        # Global timestamp of the most recent damage dealt by ANY character
        self.last_damage_timestamp: Optional[datetime] = None
        # Immunity tracking: target -> damage_type -> {max_immunity: int, max_damage: int, sample_count: int}
        # This is separate from damage events to avoid double-counting while still tracking immunity data
        self.immunity_data: Dict[str, Dict[str, Dict[str, int]]] = {}

    def insert_attack_event(self, attacker: str, target: str, outcome: str, roll: Optional[int] = None,
                           bonus: Optional[int] = None, total: Optional[int] = None) -> None:
        """Insert an attack event into the in-memory store.

        Args:
            attacker: Name of the attacking character
            target: Name of the target
            outcome: Outcome of the attack ('hit', 'miss', 'critical_hit')
            roll: The d20 roll value
            bonus: Attack bonus
            total: Total attack roll (roll + bonus)
        """
        with self.lock:
            event = AttackEvent(
                attacker=attacker,
                target=target,
                outcome=outcome,
                roll=roll,
                bonus=bonus,
                total=total
            )
            self.attacks.append(event)

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

    def update_dps_data(self, character: str, damage_amount: int, timestamp: datetime, damage_types: Optional[Dict[str, int]] = None) -> None:
        """Update DPS data for a character.

        Args:
            character: Character name dealing the damage
            damage_amount: Amount of damage dealt
            timestamp: Timestamp when the damage was dealt
            damage_types: Dictionary mapping damage type to amount for this hit
        """
        with self.lock:
            # Always update the global last damage timestamp
            if self.last_damage_timestamp is None or timestamp > self.last_damage_timestamp:
                self.last_damage_timestamp = timestamp

            if character not in self.dps_data:
                self.dps_data[character] = {
                    'total_damage': damage_amount,
                    'first_timestamp': timestamp,
                    'damage_by_type': {}
                }
            else:
                self.dps_data[character]['total_damage'] += damage_amount
                # Update first timestamp if this one is older
                if timestamp < self.dps_data[character]['first_timestamp']:
                    self.dps_data[character]['first_timestamp'] = timestamp

            # Track damage by type if provided
            if damage_types:
                if 'damage_by_type' not in self.dps_data[character]:
                    self.dps_data[character]['damage_by_type'] = {}

                for damage_type, amount in damage_types.items():
                    amount_int = int(amount or 0)
                    if damage_type not in self.dps_data[character]['damage_by_type']:
                        self.dps_data[character]['damage_by_type'][damage_type] = 0
                    self.dps_data[character]['damage_by_type'][damage_type] += amount_int

    def get_earliest_timestamp(self) -> Optional[datetime]:
        """Get the earliest timestamp from all recorded DPS data.

        Returns:
            The earliest timestamp of the first attack by any character, or None if no data
        """
        with self.lock:
            if not self.dps_data:
                return None

            earliest = None
            for character, data in self.dps_data.items():
                first_ts = data['first_timestamp']
                if earliest is None or first_ts < earliest:
                    earliest = first_ts

            return earliest

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
                        'dps': dps
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
                        'dps': dps
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
        with self.lock:
            if character not in self.dps_data:
                return []

            character_data = self.dps_data[character]

            if time_tracking_mode == "global":
                # Global mode: use global start time and global last damage timestamp
                if global_start_time is None:
                    # If global_start_time not set, use first character's first timestamp
                    if not self.dps_data:
                        return []
                    global_start_time = min(data['first_timestamp'] for data in self.dps_data.values())

                # Use the global last damage timestamp (same as per_character mode)
                if self.last_damage_timestamp is None:
                    return []

                time_delta = self.last_damage_timestamp - global_start_time
                time_seconds = max(time_delta.total_seconds(), 1)
            else:
                # Per-character mode: use character's first timestamp and global last timestamp
                if self.last_damage_timestamp is None:
                    return []

                first_ts = character_data['first_timestamp']
                last_ts = self.last_damage_timestamp

                # Calculate time elapsed in seconds
                time_delta = last_ts - first_ts
                time_seconds = max(time_delta.total_seconds(), 1)

            # Get damage by type from tracked data
            damage_by_type = character_data.get('damage_by_type', {})

            # Convert to list of dicts with DPS calculations
            breakdown = []
            for damage_type, total_dmg in damage_by_type.items():
                dps = total_dmg / time_seconds
                breakdown.append({
                    'damage_type': damage_type,
                    'total_damage': total_dmg,
                    'dps': dps
                })

            # Sort by total damage descending
            breakdown.sort(key=lambda x: x['total_damage'], reverse=True)
            return breakdown

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
        with self.lock:
            # Get damage events for this character attacking this specific target
            target_events = [e for e in self.events if e.attacker == character and e.target == target]
            if not target_events:
                return []

            # Calculate time delta based on mode
            if time_tracking_mode == "global":
                if global_start_time is None:
                    global_start_time = min(data['first_timestamp'] for data in self.dps_data.values()) if self.dps_data else datetime.now()

                # Use the global last damage timestamp (same as per_character mode)
                if self.last_damage_timestamp is None:
                    return []

                time_delta = self.last_damage_timestamp - global_start_time
                time_seconds = max(time_delta.total_seconds(), 1)
            else:
                # Per-character mode: use character's first and last attack on this target
                first_ts = min(e.timestamp for e in target_events)
                last_ts = max(e.timestamp for e in target_events)
                time_delta = last_ts - first_ts
                time_seconds = max(time_delta.total_seconds(), 1)

            # Aggregate damage by type
            damage_by_type = {}
            for event in target_events:
                dt = event.damage_type
                if dt not in damage_by_type:
                    damage_by_type[dt] = 0
                damage_by_type[dt] += event.total_damage_dealt

            # Convert to list of dicts with DPS calculations
            breakdown = []
            for damage_type, total_dmg in damage_by_type.items():
                dps = total_dmg / time_seconds
                breakdown.append({
                    'damage_type': damage_type,
                    'total_damage': total_dmg,
                    'dps': dps
                })

            # Sort by total damage descending
            breakdown.sort(key=lambda x: x['total_damage'], reverse=True)
            return breakdown

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
            targets = sorted(set(e.target for e in self.events))
            return targets

    def get_target_stats(self, target: str) -> Optional[Tuple[int, int, int]]:
        """Get overall stats for a target.

        Args:
            target: Name of the target

        Returns:
            Tuple of (total_hits, total_damage, total_absorbed) or None
        """
        with self.lock:
            target_events = [e for e in self.events if e.target == target]
            if not target_events:
                return None

            total_hits = len(target_events)
            total_damage = sum(e.total_damage_dealt for e in target_events)
            total_absorbed = sum(e.immunity_absorbed for e in target_events)
            return total_hits, total_damage, total_absorbed

    def get_attack_stats(self, attacker: str, target: str) -> Optional[dict]:
        """Get attack statistics for a specific attacker vs target.

        Args:
            attacker: Name of the attacker
            target: Name of the target

        Returns:
            Dict with keys 'attacks', 'hits', 'crits', 'misses', 'hit_rate' or None
        """
        with self.lock:
            target_attacks = [a for a in self.attacks if a.attacker == attacker and a.target == target]
            if not target_attacks:
                return None

            hits = len([a for a in target_attacks if a.outcome == 'hit'])
            crits = len([a for a in target_attacks if a.outcome == 'critical_hit'])
            misses = len([a for a in target_attacks if a.outcome == 'miss'])
            total_attacks = len(target_attacks)

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
            target_attacks = [a for a in self.attacks if a.target == target]
            if not target_attacks:
                return None

            hits = len([a for a in target_attacks if a.outcome == 'hit'])
            crits = len([a for a in target_attacks if a.outcome == 'critical_hit'])
            misses = len([a for a in target_attacks if a.outcome == 'miss'])
            total_attacks = len(target_attacks)

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
            character_hit_rates: Dict[str, float] = {}

            # Filter attacks by target if specified
            if target:
                filtered_attacks = [a for a in self.attacks if a.target == target]
            else:
                filtered_attacks = self.attacks

            # Group attacks by attacker from the filtered set
            attackers = set(a.attacker for a in filtered_attacks)

            for attacker in attackers:
                # Get this attacker's attacks from the already-filtered set
                if target:
                    attacker_attacks = [a for a in filtered_attacks if a.attacker == attacker]
                else:
                    attacker_attacks = [a for a in self.attacks if a.attacker == attacker]

                if not attacker_attacks:
                    character_hit_rates[attacker] = 0.0
                    continue

                hits = len([a for a in attacker_attacks if a.outcome == 'hit'])
                crits = len([a for a in attacker_attacks if a.outcome == 'critical_hit'])
                misses = len([a for a in attacker_attacks if a.outcome == 'miss'])

                # Calculate hit rate as (hits + crits) / (hits + crits + misses)
                successful = hits + crits
                attempted = successful + misses
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
            character_hit_rates: Dict[str, float] = {}

            # Determine which characters dealt damage
            if target:
                damage_on_target = [e for e in self.events if e.target == target and e.total_damage_dealt > 0]
                damage_dealers = set(e.attacker for e in damage_on_target)
            else:
                damage_dealers = set(e.attacker for e in self.events if e.total_damage_dealt > 0)

            # For each character who dealt damage, calculate their hit rate
            for character in damage_dealers:
                # Get all attacks by this character
                if target:
                    char_attacks = [a for a in self.attacks if a.attacker == character and a.target == target]
                else:
                    char_attacks = [a for a in self.attacks if a.attacker == character]

                if not char_attacks:
                    # Character dealt damage but no attacks recorded - default to 0%
                    character_hit_rates[character] = 0.0
                    continue

                # Calculate hit rate from actual attack data
                hits = len([a for a in char_attacks if a.outcome == 'hit'])
                crits = len([a for a in char_attacks if a.outcome == 'critical_hit'])
                misses = len([a for a in char_attacks if a.outcome == 'miss'])

                successful = hits + crits
                attempted = successful + misses
                hit_rate = (successful / attempted * 100) if attempted > 0 else 0.0

                character_hit_rates[character] = hit_rate

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

            # Filter damage events for this specific target
            damage_on_target = [e for e in self.events if e.target == target and e.total_damage_dealt > 0]
            if not damage_on_target:
                return dps_list

            # Get unique attackers for this target (from damage events)
            attackers = set(e.attacker for e in damage_on_target)

            if time_tracking_mode == "global":
                # Global mode: use global start time and global last damage timestamp
                if global_start_time is None:
                    # Use the earliest damage timestamp on this target
                    global_start_time = min(e.timestamp for e in damage_on_target)

                # Use the global last damage timestamp (same as per_character mode)
                if self.last_damage_timestamp is None:
                    return dps_list

                for character in attackers:
                    # Get total damage dealt by this character to this target only
                    char_damage_on_target = sum(
                        e.total_damage_dealt for e in self.events
                        if e.attacker == character and e.target == target
                    )

                    if char_damage_on_target == 0:
                        continue

                    time_delta = self.last_damage_timestamp - global_start_time
                    time_seconds = max(time_delta.total_seconds(), 1)
                    dps = char_damage_on_target / time_seconds

                    dps_list.append({
                        'character': character,
                        'total_damage': char_damage_on_target,
                        'time_seconds': time_delta,
                        'dps': dps
                    })
            else:
                # Per-character mode: use each character's first and last damage on this target
                for character in attackers:
                    # Get total damage dealt by this character to this target
                    char_damage_events = [
                        e for e in self.events
                        if e.attacker == character and e.target == target
                    ]

                    if not char_damage_events:
                        continue

                    char_damage_on_target = sum(e.total_damage_dealt for e in char_damage_events)

                    if char_damage_on_target == 0:
                        continue

                    # Get first and last damage timestamps (not attack timestamps)
                    first_damage_ts = min(e.timestamp for e in char_damage_events)
                    last_damage_ts = max(e.timestamp for e in char_damage_events)

                    time_delta = last_damage_ts - first_damage_ts
                    time_seconds = max(time_delta.total_seconds(), 1)
                    dps = char_damage_on_target / time_seconds

                    dps_list.append({
                        'character': character,
                        'total_damage': char_damage_on_target,
                        'time_seconds': time_delta,
                        'dps': dps
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
            target_attacks = [a for a in self.attacks if a.target == target]
            if not target_attacks:
                return None

            return min(a.timestamp for a in target_attacks if hasattr(a, 'timestamp'))


    def clear_all_data(self) -> None:
        """Clear all data from the store."""
        with self.lock:
            self.events.clear()
            self.attacks.clear()
            self.dps_data.clear()
            self.immunity_data.clear()
            self.last_damage_timestamp = None

    def close(self) -> None:
        """Close the data store (no-op for in-memory store)."""
        pass

    def get_all_damage_types(self) -> List[str]:
        """Return a sorted list of all damage types seen in the store.

        Returns:
            Sorted list of damage type names
        """
        with self.lock:
            damage_types = sorted(set(e.damage_type for e in self.events))
            return damage_types

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
            matching_events = [
                e for e in self.events
                if e.target == target and e.damage_type == damage_type
            ]
            if not matching_events:
                return 0
            return max(e.total_damage_dealt for e in matching_events)

    def get_all_targets_summary(self, parser: "LogParser") -> List[Dict]:  # type: ignore
        """Get summary data for all targets with attack bonus, AC, and saves.

        Args:
            parser: LogParser instance with target_ac, target_saves, and target_attack_bonus data

        Returns:
            List of dicts with keys: target, ab, ac, fortitude, reflex, will,
            Sorted alphabetically by target name
        """
        with self.lock:
            targets = sorted(set(e.target for e in self.events))
            summary = []

            for target in targets:
                # Get AB from parser
                ab_display = "-"
                if target in parser.target_attack_bonus:
                    ab_display = parser.target_attack_bonus[target].get_bonus_display()

                # Get AC from parser
                ac_display = "-"
                if target in parser.target_ac:
                    ac_display = parser.target_ac[target].get_ac_estimate()

                # Get saves from parser
                fort_display = "-"
                ref_display = "-"
                will_display = "-"
                if target in parser.target_saves:
                    saves = parser.target_saves[target]
                    fort_display = str(saves.fortitude) if saves.fortitude is not None else "-"
                    ref_display = str(saves.reflex) if saves.reflex is not None else "-"
                    will_display = str(saves.will) if saves.will is not None else "-"

                summary.append({
                    'target': target,
                    'ab': ab_display,
                    'ac': ac_display,
                    'fortitude': fort_display,
                    'reflex': ref_display,
                    'will': will_display
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

