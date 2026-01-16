"""Utility functions for Woo's NWN Parser.

This module contains helper functions for file parsing and data processing
that are independent of the UI.
"""

import math
from typing import Dict, List, Optional


# Forward damage logic (AUTHORITATIVE)
def compute_dmg_reduced(dmg_before_immunity: int, immunity: float) -> int:
    """
    Computes the damage reduced according to the game's rules:
    - Immunity is a percentage in steps of 5%
    - If immunity == 0 → no damage reduction
    - If immunity > 0 → at least 1 damage is shaved off

    Args:
        dmg_before_immunity: Original damage amount
        immunity: Immunity percentage (0.0 to 1.0)

    Returns:
        Damage reduced by immunity
    """
    if dmg_before_immunity <= 0:
        return 0

    if immunity <= 0:
        return 0

    raw = math.floor(dmg_before_immunity * immunity)
    return max(1, raw)


def compute_dmg_after(dmg_before_immunity: int, immunity: float) -> int:
    """
    Computes damage after immunity is applied.

    Args:
        dmg_before_immunity: Original damage amount
        immunity: Immunity percentage (0.0 to 1.0)

    Returns:
        Damage after immunity reduction
    """
    dmg_reduced = compute_dmg_reduced(dmg_before_immunity, immunity)
    return max(0, dmg_before_immunity - dmg_reduced)


# Reverse immunity % solver
def reverse_immunity(dmg_after_immunity: int, dmg_reduced: int) -> List[float]:
    """
    Returns ALL immunity values (in 5% steps) that could have produced
    the observed dmg_reduced for the given dmg_before_immunity.

    Uses mathematical bounds to optimize search space.

    Args:
        dmg_after_immunity: Damage after immunity reduction (total_damage_dealt)
        dmg_reduced: Damage reduced by immunity (immunity_absorbed)

    Returns:
        List of possible immunity percentages (0.0 to 1.0)
    """

    immunity_step = 0.01
    allowed_immunities = [i * immunity_step for i in range(int(1 / immunity_step) + 1)]
    dmg_before_immunity = dmg_after_immunity + dmg_reduced

    if dmg_before_immunity <= 0:
        return [0.0]

    if dmg_reduced <= 0:
        return [0.0]

    # Mathematical bounds: find the range where immunity could produce dmg_reduced
    min_immunity = (dmg_reduced / dmg_before_immunity) - (1 * immunity_step)
    max_immunity = (dmg_reduced / dmg_before_immunity) + (1 * immunity_step)

    matches = []
    for immunity in allowed_immunities:
        # Use bounds check to reduce unnecessary calls
        if min_immunity <= immunity <= max_immunity:
            # Verify (due to floor function edge cases)
            if compute_dmg_reduced(dmg_before_immunity, immunity) == dmg_reduced:
                matches.append(immunity)

    return matches


# Immunity picker
def pick_immunity(matches: List[float]) -> Optional[float]:
    """
    Picks a single immunity value from possible matches.
    Uses 'min' strategy for most conservative estimate.

    Args:
        matches: List of possible immunity percentages

    Returns:
        Immunity percentage as integer (0-100), or None if no matches
    """
    if not matches:
        return None

    # Use minimum as most conservative estimate
    return int(min(matches) * 100)


# Main calculation function
def calculate_immunity_percentage(max_damage: int, max_absorbed: int) -> Optional[int]:
    """
    Calculates the immunity percentage based on max damage and max absorption.

    This is the main entry point for immunity % calculation.

    Args:
        max_damage: Maximum damage dealt (per damage type)
        max_absorbed: Maximum damage absorbed (per damage type)

    Returns:
        Immunity percentage (5, 10, 15, ..., 95, 100) or None if unknown
    """
    if max_damage <= 0:
        return None

    if max_absorbed <= 0:
        return 0  # No immunity observed

    matches = reverse_immunity(max_damage, max_absorbed)
    return pick_immunity(matches)


def parse_and_import_file(file_path: str, parser, database, max_line: Optional[int] = None, progress_callback=None, progress_interval: int = 100) -> Dict:
    """Parse a log file and import data into database.

    Does not depend on GUI components, making it testable without Tkinter.

    Note: This function does NOT clear existing data. The caller should clear
    data before calling this function if needed (e.g., when processing multiple
    files, clear once before the first file, not before each file).

    Args:
        file_path: Path to the log file
        parser: LogParser instance
        database: DataStore instance
        max_line: Optional maximum line number to parse (for parsing past logs only)
        progress_callback: Optional callback function called periodically with lines_processed
        progress_interval: How often to call progress_callback (every N lines)

    Returns:
        dict with keys: 'success' (bool), 'lines_processed' (int), 'error' (str or None)
    """
    try:

        lines_processed = 0
        # Track the last damage_dealt for each target to match immunities
        last_damage_dealt = {}

        with open(file_path, 'r', encoding='utf-8', errors='ignore', buffering=65536) as f:  # 64KB buffer
            while True:
                lines = f.readlines(5000)  # Read 5000 lines per chunk
                if not lines:
                    break

                # Yield control after reading each chunk to keep UI responsive
                if progress_callback:
                    progress_callback(lines_processed)

                for line in lines:
                    lines_processed += 1

                    # Stop if we've reached the max_line (monitoring start position)
                    if max_line is not None and lines_processed > max_line:
                        return {
                            'success': True,
                            'lines_processed': lines_processed - 1,
                            'error': None
                        }


                    parsed_data = parser.parse_line(line)
                    if parsed_data:
                        if parsed_data['type'] == 'damage_dealt':
                            target = parsed_data['target']
                            attacker = parsed_data['attacker']
                            timestamp = parsed_data['timestamp']
                            total_damage = parsed_data['total_damage']

                            # Always track DPS data for all characters
                            damage_types = parsed_data.get('damage_types', {})
                            database.update_dps_data(attacker, total_damage, timestamp, damage_types)

                            # Always store target damage events for complete data tracking (consistent with monitoring behavior)
                            # Store all damage types from this damage_dealt event
                            for dt, amount in parsed_data['damage_types'].items():
                                amount_int = int(amount or 0)
                                database.insert_damage_event(target, dt, 0, amount_int, attacker, timestamp)
                            # Remember this damage event for immunity matching
                            last_damage_dealt[target] = {
                                'damage_types': parsed_data['damage_types'],
                                'timestamp': timestamp,
                                'attacker': attacker
                            }


                        elif parsed_data['type'] == 'immunity':
                            target = parsed_data['target']
                            damage_type = parsed_data['damage_type']
                            immunity_points = parsed_data['immunity_points']

                            # Try to match with the last damage_dealt for this target
                            if target in last_damage_dealt:
                                damage_types = last_damage_dealt[target]['damage_types']
                                if damage_type in damage_types:
                                    # Use the damage amount from the matched damage_dealt
                                    damage_amount = int(damage_types[damage_type] or 0)
                                    # Record immunity data separately (not as duplicate damage events)
                                    database.record_immunity(target, damage_type, immunity_points, damage_amount)

                        # Handle attack events
                        elif parsed_data['type'] == 'attack_hit':
                            database.insert_attack_event(
                                parsed_data['attacker'],
                                parsed_data['target'],
                                'hit',
                                parsed_data.get('roll'),
                                parsed_data.get('bonus'),
                                parsed_data.get('total')
                            )
                        elif parsed_data['type'] == 'attack_hit_critical':
                            database.insert_attack_event(
                                parsed_data['attacker'],
                                parsed_data['target'],
                                'critical_hit',
                                parsed_data.get('roll'),
                                parsed_data.get('bonus'),
                                parsed_data.get('total')
                            )
                        elif parsed_data['type'] == 'attack_miss':
                            database.insert_attack_event(
                                parsed_data['attacker'],
                                parsed_data['target'],
                                'miss',
                                parsed_data.get('roll'),
                                parsed_data.get('bonus'),
                                parsed_data.get('total')
                            )

        return {
            'success': True,
            'lines_processed': lines_processed,
            'error': None
        }
    except Exception as e:
        return {
            'success': False,
            'lines_processed': 0,
            'error': str(e)
        }
