"""Log parsing logic for NWN combat logs.

This module handles regex-based parsing of Neverwinter Nights game log files,
extracting damage, attack, immunity, and save information.
"""

import re
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, Optional, Pattern

from .models import EnemyAC, EnemySaves, TargetAttackBonus


MONTHS = {
    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
}


class LogParser:
    """Handles parsing of game log files to extract damage resist data."""
    DEFAULT_DEATH_FALLBACK_LINE = "Your God refuses to hear your prayers!"
    DEATH_IDENTIFY_TOKEN = "wooparseme"

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
        self._current_year = datetime.now().year

        # Pre-compile timestamp pattern for better performance
        self.timestamp_pattern = re.compile(r'\[CHAT WINDOW TEXT] \[([^]]+)]')
        self.chat_prefix_pattern = re.compile(r'^\[CHAT WINDOW TEXT]\s*\[[^]]+]\s*')

        # Pre-compile damage breakdown pattern for better performance
        self.damage_breakdown_pattern = re.compile(r"(\d+)\s+(\D+?)(?=\s+\d+|$)")

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
            ),
            # Epic Dodge indicator line for AC confidence marking
            'epic_dodge': re.compile(
                r'(?P<target>.+?)\s*:\s*Epic Dodge\s*:\s*Attack evaded',
                re.IGNORECASE
            ),
            # Player death markers (Death Snippet feature)
            'killed': re.compile(
                r'\[CHAT WINDOW TEXT]\s*\[.*?]\s*(?P<killer>.+?)\s+killed\s+(?P<target>.+?)\s*$'
            ),
            'chat_whisper': re.compile(
                r'\[CHAT WINDOW TEXT]\s*\[.*?]\s*(?P<speaker>.+?)\s*:\s*\[Whisper]\s*(?P<message>.*?)\s*$'
            ),
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

        # Death snippet extraction state (bounded ring buffer for low-memory, low-overhead scanning)
        self.death_lookup_killed_lookback_lines = 500
        self.death_snippet_max_lines = 100
        self.recent_log_lines: Deque[str] = deque(maxlen=20000)
        self._name_token_pattern_cache: Dict[str, Pattern[str]] = {}
        self._damage_immunity_marker = "Damage Immunity absorbs"
        self._attack_marker = " attacks "
        self._threat_roll_marker = "Threat Roll:"
        self._attacker_miss_chance_marker = "attacker miss chance:"
        self._target_concealed_marker = "target concealed:"
        self._save_marker = " Save"
        self._epic_dodge_marker = "Epic Dodge"
        self._killed_marker = " killed "
        self._whisper_marker = "[Whisper]"
        self.death_character_name = ""
        self._death_character_name_normalized = ""
        self.death_fallback_line = self.DEFAULT_DEATH_FALLBACK_LINE
        self._death_fallback_pattern: Optional[Pattern[str]] = self._compile_fallback_line_pattern(
            self.death_fallback_line
        )

    @staticmethod
    def _normalize_name(value: str) -> str:
        """Trim and normalize a character name string."""
        return " ".join(value.strip().split())

    def set_death_character_name(self, name: str) -> None:
        """Set character name used for character-specific death detection."""
        normalized = self._normalize_name(name)
        self.death_character_name = normalized
        self._death_character_name_normalized = normalized

    @staticmethod
    def _compile_fallback_line_pattern(value: str) -> Optional[Pattern[str]]:
        """Compile a fallback death-line matcher from exact line text."""
        normalized = value.strip()
        if not normalized:
            return None
        return re.compile(rf'\[CHAT WINDOW TEXT]\s*\[.*?]\s*{re.escape(normalized)}\s*$')

    def set_death_fallback_line(self, line: str) -> None:
        """Set fallback death line used when character name is unknown."""
        self.death_fallback_line = line.strip()
        self._death_fallback_pattern = self._compile_fallback_line_pattern(self.death_fallback_line)

    def _get_name_token_pattern(self, character_name: str) -> Pattern[str]:
        """Get cached exact-token, case-sensitive regex for a character name."""
        cached = self._name_token_pattern_cache.get(character_name)
        if cached is not None:
            return cached

        # Exact token boundaries with case-sensitive matching.
        pattern = re.compile(rf'(?<!\w){re.escape(character_name)}(?!\w)')
        self._name_token_pattern_cache[character_name] = pattern
        return pattern

    def _collect_death_snippet_lines(
        self,
        *,
        history: list[str],
        target_name: str,
        trigger_line: Optional[str] = None,
    ) -> Optional[list[str]]:
        """Collect up to max recent lines that mention the target name."""
        if not target_name:
            return None

        name_pattern = self._get_name_token_pattern(target_name)
        snippet_reversed = []
        for candidate in reversed(history):
            if name_pattern.search(candidate):
                snippet_reversed.append(candidate)
                if len(snippet_reversed) >= self.death_snippet_max_lines:
                    break

        if not snippet_reversed:
            return None

        snippet_lines = list(reversed(snippet_reversed))
        if trigger_line and (not snippet_lines or snippet_lines[-1] != trigger_line):
            snippet_lines.append(trigger_line)
        return snippet_lines

    def _build_death_snippet_event_from_fallback(
        self,
        fallback_line: str,
        timestamp: datetime,
    ) -> Optional[Dict[str, Any]]:
        """Build a death snippet event by scanning backward from the prayer line."""
        if len(self.recent_log_lines) < 2:
            return None

        # Exclude current prayer line; scan recent history backward for nearest kill line.
        history = list(self.recent_log_lines)[:-1]
        killed_match = None
        scanned = 0
        for candidate in reversed(history):
            if scanned >= self.death_lookup_killed_lookback_lines:
                break
            scanned += 1
            m = self.patterns['killed'].search(candidate)
            if m:
                killed_match = m
                break

        if not killed_match:
            return None

        dead_target = killed_match.group('target').strip()
        killer = killed_match.group('killer').strip()
        if not dead_target:
            return None

        snippet_lines = self._collect_death_snippet_lines(
            history=history,
            target_name=dead_target,
            trigger_line=fallback_line,
        )
        if not snippet_lines:
            return None

        return {
            'type': 'death_snippet',
            'target': dead_target,
            'killer': killer,
            'lines': snippet_lines,
            'timestamp': timestamp,
        }

    def _build_death_snippet_event_from_killed_match(
        self,
        *,
        killer: str,
        target: str,
        timestamp: datetime,
    ) -> Optional[Dict[str, Any]]:
        """Build death snippet event using current killed line as trigger."""
        history = list(self.recent_log_lines)
        snippet_lines = self._collect_death_snippet_lines(
            history=history,
            target_name=target,
        )
        if not snippet_lines:
            return None

        return {
            'type': 'death_snippet',
            'target': target,
            'killer': killer,
            'lines': snippet_lines,
            'timestamp': timestamp,
        }

    def extract_timestamp_from_line(self, line: str) -> Optional[datetime]:
        """Extract timestamp from a log line.

        Expected format: [CHAT WINDOW TEXT] [Wed Dec 31 21:07:37] ...

        Args:
            line: A log line string

        Returns:
            datetime object or None if parsing fails
        """
        try:
            # Use pre-compiled pattern for better performance
            match = self.timestamp_pattern.search(line)
            if match:
                timestamp_str = match.group(1)
                # Expected format: "Wed Dec 31 21:07:37" (Day Mon DD HH:MM:SS)
                # Manual parsing for performance while preserving date for midnight crossing accuracy
                parts = timestamp_str.split(maxsplit=3)
                if len(parts) == 4:
                    month = MONTHS.get(parts[1])
                    if month is None:
                        return None

                    time_part = parts[3]
                    if len(time_part) != 8 or time_part[2] != ':' or time_part[5] != ':':
                        return None

                    day = int(parts[2])
                    hour = int(time_part[0:2])
                    minute = int(time_part[3:5])
                    second = int(time_part[6:8])

                    # Create datetime with full date to handle midnight crossings correctly
                    return datetime(self._current_year, month, day, hour, minute, second)
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
        # Use pre-compiled pattern for better performance
        for m in self.damage_breakdown_pattern.finditer(breakdown_str):
            amt = int(m.group(1))
            # Damage type string may have trailing/leading spaces; normalize internal whitespace
            raw_dtype = m.group(2).strip()
            dtype = ' '.join(raw_dtype.split()) if '  ' in raw_dtype else raw_dtype
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

        raw_line = line.rstrip('\r\n')
        self.recent_log_lines.append(raw_line)
        timestamp: Optional[datetime] = None
        patterns = self.patterns

        def get_timestamp() -> datetime:
            nonlocal timestamp
            if timestamp is None:
                timestamp = self.extract_timestamp_from_line(line)
                if not timestamp:
                    timestamp = datetime.now()
            return timestamp

        if self._whisper_marker in raw_line:
            whisper_match = patterns['chat_whisper'].search(raw_line)
            if whisper_match:
                message = str(whisper_match.group("message")).strip()
                if message.casefold() == self.DEATH_IDENTIFY_TOKEN:
                    speaker = self._normalize_name(str(whisper_match.group("speaker")))
                    if speaker:
                        self.set_death_character_name(speaker)
                        return {
                            'type': 'death_character_identified',
                            'character_name': speaker,
                            'timestamp': get_timestamp(),
                        }

        if self._killed_marker in raw_line and self._death_character_name_normalized:
            killed_match = patterns['killed'].search(raw_line)
            if killed_match:
                dead_target = self._normalize_name(str(killed_match.group('target')))
                if dead_target == self._death_character_name_normalized:
                    killer = self._normalize_name(str(killed_match.group('killer')))
                    death_event = self._build_death_snippet_event_from_killed_match(
                        killer=killer,
                        target=dead_target,
                        timestamp=get_timestamp(),
                    )
                    if death_event:
                        return death_event

        # Death Snippet fallback is active only while character name is unknown.
        if (not self._death_character_name_normalized) and self._death_fallback_pattern:
            fallback_match = self._death_fallback_pattern.search(raw_line)
            if fallback_match:
                death_event = self._build_death_snippet_event_from_fallback(raw_line, get_timestamp())
                if death_event:
                    return death_event

        # Check for damage dealt (this sets the context for subsequent resist lines)
        damage_match = patterns['damage_dealt'].search(raw_line)

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
                'timestamp': get_timestamp(),
                'filtered_for_player': self.player_name and attacker != self.player_name
            }

        # Damage immunity lines are common enough to warrant a fast substring gate.
        # When immunity parsing is disabled, exit early instead of paying for the
        # attack/save path on lines we already know we will ignore.
        if self._damage_immunity_marker in raw_line:
            if not self.parse_immunity:
                return None

            immunity_match = patterns['damage_immunity'].search(raw_line)
            if not immunity_match:
                return None

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
                'timestamp': get_timestamp()
            }

        # Strip [CHAT WINDOW TEXT] prefix for attack and save patterns.
        stripped_line = raw_line
        if raw_line.startswith('[CHAT WINDOW TEXT] ['):
            close_idx = raw_line.find('] ', len('[CHAT WINDOW TEXT] ['))
            if close_idx != -1:
                stripped_line = raw_line[close_idx + 2:]
            else:
                prefix_match = self.chat_prefix_pattern.match(raw_line)
                if prefix_match:
                    stripped_line = raw_line[prefix_match.end():]
        else:
            prefix_match = self.chat_prefix_pattern.match(raw_line)
            if prefix_match:
                stripped_line = raw_line[prefix_match.end():]

        # Check for Epic Dodge markers and tag the target AC estimate as uncertain.
        if self._epic_dodge_marker in stripped_line:
            epic_dodge_match = patterns['epic_dodge'].search(stripped_line)
            if epic_dodge_match:
                target = epic_dodge_match.group('target').strip()
                if target not in self.target_ac:
                    self.target_ac[target] = EnemyAC(name=target)
                self.target_ac[target].mark_epic_dodge()
                return None

        # Check for attack rolls to estimate AC. Most lines are plain hit/miss entries,
        # so route to the narrowest plausible regex first.
        if self._attack_marker in stripped_line:
            if self._target_concealed_marker in stripped_line:
                attack_match = self.patterns['attack_conceal'].search(stripped_line)
            elif (
                self._threat_roll_marker in stripped_line or
                self._attacker_miss_chance_marker in stripped_line
            ):
                attack_match = patterns['attack_with_threat'].search(stripped_line)
            else:
                attack_match = patterns['attack'].search(stripped_line)
        else:
            attack_match = None

        if attack_match:
            attacker = attack_match.group('attacker').strip()
            target = attack_match.group('target').strip()
            outcome = attack_match.group('outcome').lower() if 'outcome' in attack_match.groupdict() else ''

            # Parse roll results
            roll_str = attack_match.group('roll')
            total_str = attack_match.group('total')

            # Handle outcomes including special miss chance
            # outcome can only be: hit, critical hit, miss, parried, resisted, or attacker miss chance
            is_hit = 'hit' in outcome
            is_crit = 'critical' in outcome
            is_miss = 'miss' in outcome or 'parried' in outcome or 'resisted' in outcome
            is_concealment = 'attacker miss chance' in outcome

            if roll_str and total_str:
                roll = int(roll_str)
                total = int(total_str)
                was_nat1 = roll == 1
                was_nat20 = roll == 20
                bonus_str = attack_match.group('bonus')
                bonus = int(bonus_str) if bonus_str else None

                # Track AC for all attacks against targets (for AC estimation)
                # EXCEPT concealment misses which don't reveal AC information
                # Initialize target tracking if needed
                if target not in self.target_ac and not is_concealment:
                    self.target_ac[target] = EnemyAC(name=target)

                if is_hit:
                    self.target_ac[target].record_hit(total, was_nat20)
                elif is_miss and not is_concealment:
                    # Exclude concealment misses from AC estimation
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
                        'timestamp': get_timestamp()
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
                        'timestamp': get_timestamp()
                    }

        # Check for save rolls to estimate saves
        save_match = None
        if self._save_marker in stripped_line:
            save_match = patterns['save'].search(stripped_line)
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
                    'timestamp': get_timestamp()
                }

        return None

