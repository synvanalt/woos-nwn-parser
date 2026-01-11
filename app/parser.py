"""Log parsing logic for NWN combat logs.

This module handles regex-based parsing of Neverwinter Nights game log files,
extracting damage, attack, immunity, and save information.
"""

import re
from datetime import datetime
from typing import Dict, Optional

from .models import EnemyAC, EnemySaves, TargetAttackBonus


class LogParser:
    """Handles parsing of game log files to extract damage resist data."""

    def __init__(self, player_name: Optional[str] = None, parse_immunity: bool = False) -> None:
        """Initialize the parser.

        Args:
            player_name: Name of the player character (used to filter attacks)
            parse_immunity: Whether to parse damage immunity lines
        """
        self.player_name = player_name
        # Whether to attempt to parse damage immunity lines. Can be toggled at runtime
        # to reduce runtime work. Default is False (OFF) as requested.
        self.parse_immunity = bool(parse_immunity)

        # Patterns for parsing the log format
        self.patterns = {
            # Flexible damage pattern - skip [CHAT WINDOW TEXT] and timestamp, then capture attacker
            'damage_dealt': re.compile(
                r'\[CHAT WINDOW TEXT] \[.*?] (.+?) damages ([^:]+): (\d+) \(([^)]+)\)'
            ),
            # Keep the immunity pattern defined but only used when self.parse_immunity is True
            'damage_immunity': re.compile(
                r'\[CHAT WINDOW TEXT] \[.*?] (.+?) : Damage Immunity absorbs (\d+) point(?:\(s\)|s)? of (.+)'
            ),
            # Attack pattern for AC estimation
            'attack': re.compile(
                r'(?:Off Hand\s*:\s*)?'  # Optional "Off Hand : " prefix
                r'(?:[\w\s]+\s*:\s*)*'  # Zero or more ability name prefixes (e.g., "Flurry of Blows : Sneak Attack : ")
                r'(?:Attack Of Opportunity\s*:\s*)?'  # Optional "Attack Of Opportunity : " prefix
                r'(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*'
                r'\*(?P<outcome>hit|miss|critical hit|parried|resisted)\*\s*'
                r'(?::\s*\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)\))?',
                re.IGNORECASE
            ),
            # Attack with concealment pattern
            'attack_conceal': re.compile(
                r'(?:Off Hand\s*:\s*)?'  # Optional "Off Hand : " prefix
                r'(?:[\w\s]+\s*:\s*)*'  # Zero or more ability name prefixes (e.g., "Flurry of Blows : Sneak Attack : ")
                r'(?:Attack Of Opportunity\s*:\s*)?'  # Optional "Attack Of Opportunity : " prefix
                r'(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*'
                r'\*target concealed:\s*(?P<conceal>\d+)%\*\s*:\s*'
                r'\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)\)\s*:\s*'
                r'\*(?P<outcome>hit|miss|critical hit|parried|resisted)\*',
                re.IGNORECASE
            ),
            # Attack pattern that matches critical hit with optional threat roll
            'attack_with_threat': re.compile(
                r'(?:Off Hand\s*:\s*)?'  # Optional "Off Hand : " prefix
                r'(?:[\w\s]+\s*:\s*)*'  # Zero or more ability name prefixes (e.g., "Flurry of Blows : Sneak Attack : ")
                r'(?:Attack Of Opportunity\s*:\s*)?'  # Optional "Attack Of Opportunity : " prefix
                r'(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*'
                r'\*(?P<outcome>hit|critical hit|miss|parried|resisted|attacker miss chance:\s*\d+%)\*'
                r'(?:\s*:\s*\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)'
                r'(?:\s*:\s*Threat Roll:.*?)?\))?',
                re.IGNORECASE
            ),
            # Save pattern for save estimation
            'save': re.compile(
                r'(?:SAVE:\s*)?(?P<target>.+?)\s*:\s*'
                r'(?P<save_type>Fort|Fortitude|Reflex|Will)\s+Save(?:\s+vs\.\s*[^:]+?)?\s*:\s*'
                r'\*(?P<outcome>success|failed)\*\s*:\s*'
                r'\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*(?:=\s*\d+\s*)?vs\.\s*DC:\s*(?P<dc>\d+)\)',
                re.IGNORECASE
            )
        }

        self.current_target = None
        self.current_damage_types = {}
        self.pending_resists = {}
        self.damage_type_queue = []  # Track order of damage types to process
        self.current_processing_type = None  # Which damage type we're currently processing resists for

        # Target tracking for AC, Saves, and Attack Bonus
        self.target_ac: Dict[str, EnemyAC] = {}
        self.target_saves: Dict[str, EnemySaves] = {}
        self.target_attack_bonus: Dict[str, TargetAttackBonus] = {}

    def extract_timestamp_from_line(self, line: str) -> Optional[datetime]:
        """Extract timestamp from a log line.

        Expected format: [CHAT WINDOW TEXT] [Wed Dec 31 21:07:37] ...

        Args:
            line: A log line string

        Returns:
            datetime object or None if parsing fails
        """
        try:
            # Match the timestamp between square brackets after [CHAT WINDOW TEXT]
            match = re.search(r'\[CHAT WINDOW TEXT\]\s+\[([^\]]+)\]', line)
            if match:
                timestamp_str = match.group(1)
                # Expected format: "Wed Dec 31 21:07:37"
                # Extract just the time portion (HH:MM:SS)
                time_match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})', timestamp_str)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))
                    second = int(time_match.group(3))
                    # Create a datetime with today's date and the extracted time
                    return datetime.now().replace(hour=hour, minute=minute, second=second, microsecond=0)
        except Exception:
            pass
        return None

    def parse_damage_breakdown(self, breakdown_str: str) -> Dict[str, int]:
        """Parse the flexible damage breakdown string.

        Example: '21 Physical 4 Divine 3 Fire 13 Positive Energy 1 Pure'

        This implementation uses a regex to capture pairs of (number, damage type string)
        where damage type may be multiple words.

        Args:
            breakdown_str: The damage breakdown portion of a log line

        Returns:
            Dictionary mapping damage type names to amounts
        """
        damage_types = {}
        if not breakdown_str:
            return damage_types

        # Match sequences like: <number><space><damage type words> (until next number or end)
        # Example matches: '21 Physical', '13 Positive Energy', '1 Pure'
        pattern = re.compile(r"(\d+)\s+([^\d]+?)(?=\s+\d+|$)")
        for m in pattern.finditer(breakdown_str):
            amt = int(m.group(1))
            # Damage type string may have trailing/leading spaces; normalize internal whitespace
            dtype = ' '.join(m.group(2).strip().split())
            damage_types[dtype] = amt

        return damage_types

    def parse_line(self, line: str) -> Optional[Dict]:
        """Parse a single log line and extract relevant data.

        Args:
            line: A single line from the log file

        Returns:
            Dictionary with parsed data or None if line doesn't match any pattern
        """
        if not line.strip():
            return None

        # Extract timestamp from the log line
        timestamp = self.extract_timestamp_from_line(line)
        if not timestamp:
            timestamp = datetime.now()

        # Check for damage dealt (this sets the context for subsequent resist lines)
        damage_match = self.patterns['damage_dealt'].search(line)

        if damage_match:
            attacker = damage_match.group(1).strip()
            target = damage_match.group(2).strip()
            total_damage = int(damage_match.group(3))
            breakdown_str = damage_match.group(4)

            # Parse the flexible damage breakdown
            self.current_target = target
            self.current_damage_types = self.parse_damage_breakdown(breakdown_str)

            # Create queue of damage types in order they appear
            self.damage_type_queue = list(self.current_damage_types.keys())
            self.current_processing_type = self.damage_type_queue[0] if self.damage_type_queue else None
            self.pending_resists[target] = {}

            return {
                'type': 'damage_dealt',
                'attacker': attacker,
                'target': target,
                'total_damage': total_damage,
                'damage_types': self.current_damage_types,
                'timestamp': timestamp,
                'filtered_for_player': self.player_name and attacker != self.player_name
            }

        # Check for damage immunity
        # Skip attempting to parse immunity lines if the parser is configured to not do so
        immunity_match = None
        if self.parse_immunity:
            immunity_match = self.patterns['damage_immunity'].search(line)
        if immunity_match:
            target = immunity_match.group(1).strip()
            immunity_points = int(immunity_match.group(2))
            damage_type = immunity_match.group(3).strip()

            # Immunity explicitly states the damage type - use it to sync our queue position
            if target == self.current_target and damage_type in self.damage_type_queue:
                self.current_processing_type = damage_type

            if target not in self.pending_resists:
                self.pending_resists[target] = {}

            if damage_type not in self.pending_resists[target]:
                self.pending_resists[target][damage_type] = {'immunity': 0, 'resistance': 0, 'reduction': 0}

            # Store immunity as raw points (consistent with earlier behavior / DB schema)
            self.pending_resists[target][damage_type]['immunity'] = immunity_points

            # Return parsed immunity data (use raw points for immunity_points)
            return {
                'type': 'immunity',
                'target': target,
                'damage_type': damage_type,
                'immunity_points': immunity_points,
                'dmg_reduced': immunity_points,
                'timestamp': timestamp
            }

        # Strip [CHAT WINDOW TEXT] prefix for attack and save patterns
        stripped_line = line
        if '[CHAT WINDOW TEXT]' in line:
            # Remove the [CHAT WINDOW TEXT] [timestamp] prefix
            stripped_line = re.sub(r'^\[CHAT WINDOW TEXT\]\s*\[[^\]]+\]\s*', '', line)

        # Check for attack rolls to estimate AC - try threat roll pattern first (handles critical hits)
        attack_match = self.patterns['attack_with_threat'].search(stripped_line)
        if not attack_match:
            attack_match = self.patterns['attack_conceal'].search(stripped_line)
        if not attack_match:
            attack_match = self.patterns['attack'].search(stripped_line)

        if attack_match:
            attacker = attack_match.group('attacker').strip()
            target = attack_match.group('target').strip()
            outcome = attack_match.group('outcome').lower() if 'outcome' in attack_match.groupdict() else ''

            # Parse roll results
            roll_str = attack_match.group('roll')
            total_str = attack_match.group('total')

            # Handle outcomes including special miss chance
            is_hit = 'hit' in outcome and 'miss' not in outcome and 'attacker miss chance' not in outcome
            is_crit = 'critical' in outcome
            is_miss = 'miss' in outcome or 'parried' in outcome or 'resisted' in outcome or 'attacker miss chance' in outcome

            if roll_str and total_str:
                roll = int(roll_str)
                total = int(total_str)
                was_nat1 = roll == 1
                bonus_str = attack_match.group('bonus')
                bonus = int(bonus_str) if bonus_str else None

                # Track AC for all attacks against targets (for AC estimation)
                # Initialize target tracking if needed
                if target not in self.target_ac:
                    self.target_ac[target] = EnemyAC(name=target)

                if is_hit:
                    self.target_ac[target].record_hit(total)
                elif is_miss:
                    self.target_ac[target].record_miss(total, was_nat1)

                # Track attack bonus for the ATTACKER (when they attack others)
                # This shows what AB the target uses when it attacks
                if bonus is not None:
                    if attacker not in self.target_attack_bonus:
                        self.target_attack_bonus[attacker] = TargetAttackBonus(name=attacker)
                    self.target_attack_bonus[attacker].record_bonus(bonus)

                # Track all attacks for hit rate calculation (all characters)
                if is_hit:
                    return {
                        'type': 'attack_hit_critical' if is_crit else 'attack_hit',
                        'attacker': attacker,
                        'target': target,
                        'roll': roll,
                        'bonus': bonus_str,
                        'total': total,
                        'timestamp': timestamp
                    }
                elif is_miss:
                    return {
                        'type': 'attack_miss',
                        'attacker': attacker,
                        'target': target,
                        'roll': roll,
                        'bonus': attack_match.group('bonus'),
                        'total': total,
                        'was_nat1': was_nat1,
                        'timestamp': timestamp
                    }

        # Check for save rolls to estimate saves
        save_match = self.patterns['save'].search(stripped_line)
        if save_match:
            target = save_match.group('target').strip()
            save_type = save_match.group('save_type').lower()
            bonus_str = save_match.group('bonus')

            if bonus_str:
                bonus = int(bonus_str)

                # Initialize target tracking if needed
                if target not in self.target_saves:
                    self.target_saves[target] = EnemySaves(name=target)

                # Map save type to key
                if save_type in ('fort', 'fortitude'):
                    save_key = 'fort'
                elif save_type == 'reflex':
                    save_key = 'ref'
                else:
                    save_key = 'will'

                self.target_saves[target].update_save(save_key, bonus)

                return {
                    'type': 'save',
                    'target': target,
                    'save_type': save_key,
                    'bonus': bonus,
                    'timestamp': timestamp
                }

        return None

