"""Pure per-line parser for NWN combat logs."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional

from .parsed_events import (
    AttackCriticalHitEvent,
    AttackHitEvent,
    AttackMissEvent,
    DamageDealtEvent,
    EpicDodgeEvent,
    ImmunityObservedEvent,
    ParsedEvent,
    SaveObservedEvent,
)


MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


class LineParser:
    """Stateless single-line parser for combat log syntax."""

    DEATH_IDENTIFY_TOKEN = "wooparseme"

    def __init__(
        self,
        *,
        player_name: Optional[str] = None,
        parse_immunity: bool = True,
    ) -> None:
        self.player_name = player_name
        self.parse_immunity = bool(parse_immunity)

        self.timestamp_pattern = re.compile(r"\[CHAT WINDOW TEXT] \[([^]]+)]")
        self.chat_prefix_pattern = re.compile(r"^\[CHAT WINDOW TEXT]\s*\[[^]]+]\s*")
        self.patterns = {
            "damage_dealt": re.compile(
                r"\[CHAT WINDOW TEXT] \[.*?] (.+?) damages ([^:]+): (\d+) \(([^)]+)\)"
            ),
            "damage_immunity": re.compile(
                r"\[CHAT WINDOW TEXT] \[.*?] (.+?) : Damage Immunity absorbs (\d+) point(?:\(s\)|s)? of (.+)"
            ),
            "attack": re.compile(
                r"(?:Off Hand\s*:\s*)?"
                r"(?:[\w\s]+\s*:\s*)*"
                r"(?:Attack Of Opportunity\s*:\s*)?"
                r"(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*"
                r"\*(?P<outcome>hit|miss|critical hit|parried|resisted)\*\s*"
                r"(?::\s*\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)\))?",
                re.IGNORECASE,
            ),
            "attack_conceal": re.compile(
                r"(?:Off Hand\s*:\s*)?"
                r"(?:[\w\s]+\s*:\s*)*"
                r"(?:Attack Of Opportunity\s*:\s*)?"
                r"(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*"
                r"\*target concealed:\s*(?P<conceal>\d+)%\*\s*:\s*"
                r"\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)\)\s*:\s*"
                r"\*(?P<outcome>hit|miss|critical hit|parried|resisted)\*",
                re.IGNORECASE,
            ),
            "attack_with_threat": re.compile(
                r"(?:Off Hand\s*:\s*)?"
                r"(?:[\w\s]+\s*:\s*)*"
                r"(?:Attack Of Opportunity\s*:\s*)?"
                r"(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*"
                r"\*(?P<outcome>hit|critical hit|miss|parried|resisted|attacker miss chance:\s*\d+%)\*"
                r"(?:\s*:\s*\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)"
                r"(?:\s*:\s*Threat Roll:.*?)?\))?",
                re.IGNORECASE,
            ),
            "save": re.compile(
                r"(?:SAVE:\s*)?(?P<target>.+?)\s*:\s*"
                r"(?P<save_type>Fort|Fortitude|Reflex|Will)\s+Save(?:\s+vs\.\s*[^:]+?)?\s*:\s*"
                r"\*(?P<outcome>success|failed)\*\s*:\s*"
                r"\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*(?:=\s*\d+\s*)?vs\.\s*DC:\s*(?P<dc>\d+)\)",
                re.IGNORECASE,
            ),
            "epic_dodge": re.compile(
                r"(?P<target>.+?)\s*:\s*Epic Dodge\s*:\s*Attack evaded",
                re.IGNORECASE,
            ),
            "killed": re.compile(
                r"\[CHAT WINDOW TEXT]\s*\[.*?]\s*(?P<killer>.+?)\s+killed\s+(?P<target>.+?)\s*$"
            ),
            "chat_whisper": re.compile(
                r"\[CHAT WINDOW TEXT]\s*\[.*?]\s*(?P<speaker>.+?)\s*:\s*\[Whisper]\s*(?P<message>.*?)\s*$"
            ),
        }

        self._damage_immunity_marker = "Damage Immunity absorbs"
        self._attack_marker = " attacks "
        self._threat_roll_marker = "Threat Roll:"
        self._attacker_miss_chance_marker = "attacker miss chance:"
        self._target_concealed_marker = "target concealed:"
        self._save_marker = " Save"
        self._epic_dodge_marker = "Epic Dodge"
        self._killed_marker = " killed "
        self._whisper_marker = "[Whisper]"

    @staticmethod
    def normalize_name(value: str) -> str:
        """Trim and normalize a character name string."""
        return " ".join(value.strip().split())

    def extract_timestamp_parts(self, line: str) -> Optional[tuple[int, int, int, int, int]]:
        """Extract month/day/time components without resolving a year."""
        match = self.timestamp_pattern.search(line)
        if not match:
            return None

        timestamp_str = match.group(1)
        parts = timestamp_str.split(maxsplit=3)
        if len(parts) != 4:
            return None

        month = MONTHS.get(parts[1])
        if month is None:
            return None

        time_part = parts[3]
        if len(time_part) != 8 or time_part[2] != ":" or time_part[5] != ":":
            return None

        try:
            day = int(parts[2])
            hour = int(time_part[0:2])
            minute = int(time_part[3:5])
            second = int(time_part[6:8])
        except ValueError:
            return None

        return month, day, hour, minute, second

    def build_timestamp(self, line: str, *, year: int) -> Optional[datetime]:
        """Build a timestamp for a line using a caller-supplied year."""
        parts = self.extract_timestamp_parts(line)
        if parts is None:
            return None

        month, day, hour, minute, second = parts
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None

    def parse_damage_breakdown(self, breakdown_str: str) -> Dict[str, int]:
        """Parse the flexible damage breakdown string."""
        damage_types: Dict[str, int] = {}
        if not breakdown_str:
            return damage_types

        tokens = breakdown_str.split()
        index = 0
        token_count = len(tokens)
        while index < token_count:
            while index < token_count and not tokens[index].isdigit():
                index += 1
            if index >= token_count:
                break

            amount = int(tokens[index])
            index += 1
            type_start = index
            while index < token_count and not tokens[index].isdigit():
                index += 1
            if type_start < index:
                damage_types[" ".join(tokens[type_start:index])] = amount

        return damage_types

    @staticmethod
    def _normalize_attack_attacker_name(raw_attacker: str) -> str:
        attacker = raw_attacker.strip()
        if " : " in attacker:
            attacker = attacker.rsplit(" : ", 1)[-1].strip()
        return attacker

    def _parse_attack_threat_fast(self, s: str) -> tuple[Optional[Dict[str, Any]], bool]:
        if self._attack_marker not in s or self._threat_roll_marker not in s:
            return None, True

        attack_idx = s.find(self._attack_marker)
        if attack_idx < 0:
            return None, True

        attacker = self._normalize_attack_attacker_name(s[:attack_idx])
        rest = s[attack_idx + len(self._attack_marker):]
        star_start = rest.find("*")
        if star_start < 0:
            return None, True

        target = rest[:star_start].rstrip(" :").strip()
        if not target:
            return None, True

        star_end = rest.find("*", star_start + 1)
        if star_end < 0:
            return None, True

        outcome = rest[star_start + 1:star_end].strip().lower()
        if outcome not in {"hit", "critical hit", "miss", "parried", "resisted"}:
            return None, True

        roll_start = rest.find("(", star_end)
        roll_end = rest.find(")", roll_start + 1)
        if roll_start < 0 or roll_end < 0:
            return None, True

        roll_expr = rest[roll_start + 1:roll_end]
        plus_idx = roll_expr.find("+")
        equals_idx = roll_expr.find("=", plus_idx + 1)
        if plus_idx < 0 or equals_idx < 0:
            return None, True

        roll_str = roll_expr[:plus_idx].strip()
        bonus_str = roll_expr[plus_idx + 1:equals_idx].strip()
        total_tail = roll_expr[equals_idx + 1:].strip()
        if not roll_str or not bonus_str or not total_tail:
            return None, True

        total_end = 0
        while total_end < len(total_tail) and total_tail[total_end].isdigit():
            total_end += 1
        if total_end == 0:
            return None, True

        return {
            "attacker": attacker,
            "target": target,
            "outcome": outcome,
            "roll": roll_str,
            "bonus": bonus_str,
            "total": total_tail[:total_end],
        }, False

    def _parse_attack_basic_fast(self, s: str) -> tuple[Optional[Dict[str, Any]], bool]:
        if self._attack_marker not in s:
            return None, True

        attack_idx = s.find(self._attack_marker)
        if attack_idx < 0:
            return None, True

        attacker = self._normalize_attack_attacker_name(s[:attack_idx])
        rest = s[attack_idx + len(self._attack_marker):]
        star_start = rest.find("*")
        if star_start < 0:
            return None, True

        target = rest[:star_start].rstrip(" :").strip()
        if not target:
            return None, True

        star_end = rest.find("*", star_start + 1)
        if star_end < 0:
            return None, True

        outcome = rest[star_start + 1:star_end].strip().lower()
        if outcome not in {"hit", "critical hit", "miss", "parried", "resisted"}:
            return None, True

        tail = rest[star_end + 1:].strip()
        if not tail:
            return {"attacker": attacker, "target": target, "outcome": outcome, "roll": None, "bonus": None, "total": None}, False
        if tail.startswith(":"):
            tail = tail[1:].strip()
        if not tail:
            return {"attacker": attacker, "target": target, "outcome": outcome, "roll": None, "bonus": None, "total": None}, False

        roll_start = tail.find("(")
        roll_end = tail.find(")", roll_start + 1)
        if roll_start < 0 or roll_end < 0:
            return None, True

        roll_expr = tail[roll_start + 1:roll_end]
        plus_idx = roll_expr.find("+")
        equals_idx = roll_expr.find("=", plus_idx + 1)
        if plus_idx < 0 or equals_idx < 0:
            return None, True

        roll_str = roll_expr[:plus_idx].strip()
        bonus_str = roll_expr[plus_idx + 1:equals_idx].strip()
        total_str = roll_expr[equals_idx + 1:].strip()
        if not roll_str or not bonus_str or not total_str:
            return None, True

        return {
            "attacker": attacker,
            "target": target,
            "outcome": outcome,
            "roll": roll_str,
            "bonus": bonus_str,
            "total": total_str,
        }, False

    def _parse_attack_conceal_fast(self, s: str) -> tuple[Optional[Dict[str, Any]], bool]:
        if " attacks " not in s or "*target concealed:" not in s:
            return None, True
        try:
            left, right = s.split(" attacks ", 1)
            target_part, rest = right.split(" : *target concealed:", 1)
            roll_seg_start = rest.find("(")
            roll_seg_end = rest.find(")", roll_seg_start + 1)
            if roll_seg_start < 0 or roll_seg_end < 0:
                return None, True

            roll_expr = rest[roll_seg_start + 1:roll_seg_end]
            roll_s, rem = roll_expr.split("+", 1)
            bonus_s, total_s = rem.split("=", 1)

            attacker = self._normalize_attack_attacker_name(left)
            target = target_part.strip()
            roll = int(roll_s.strip())
            bonus = int(bonus_s.strip())
            total = int(total_s.strip())

            tail = rest[roll_seg_end + 1:].strip()
            if not tail:
                return None, False
            if tail.startswith(":"):
                tail = tail[1:].strip()
            if not tail:
                return None, False
            if not tail.startswith("*"):
                return None, True

            end_star = tail.find("*", 1)
            if end_star < 0:
                return None, True

            outcome = tail[1:end_star].strip().lower()
            if outcome not in {"hit", "critical hit", "miss", "parried", "resisted"}:
                return None, True

            return {
                "attacker": attacker,
                "target": target,
                "outcome": outcome,
                "roll": roll,
                "bonus": str(bonus),
                "total": total,
            }, False
        except ValueError:
            return None, True

    def _strip_chat_prefix(self, raw_line: str) -> str:
        stripped_line = raw_line
        if raw_line.startswith("[CHAT WINDOW TEXT] ["):
            close_idx = raw_line.find("] ", len("[CHAT WINDOW TEXT] ["))
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
        return stripped_line

    def parse_line(
        self,
        raw_line: str,
        *,
        line_number: int,
        get_timestamp: Any,
    ) -> Optional[ParsedEvent]:
        """Parse a non-empty raw line without session history state."""
        patterns = self.patterns

        damage_match = patterns["damage_dealt"].search(raw_line)
        if damage_match:
            return DamageDealtEvent(
                attacker=damage_match.group(1).strip(),
                target=damage_match.group(2).strip(),
                total_damage=int(damage_match.group(3)),
                damage_types=self.parse_damage_breakdown(damage_match.group(4)),
                timestamp=get_timestamp(),
                line_number=line_number,
            )

        if self._damage_immunity_marker in raw_line:
            if not self.parse_immunity:
                return None

            immunity_match = patterns["damage_immunity"].search(raw_line)
            if not immunity_match:
                return None

            target = immunity_match.group(1).strip()
            immunity_points = int(immunity_match.group(2))
            damage_type = immunity_match.group(3).strip()
            return ImmunityObservedEvent(
                target=target,
                damage_type=damage_type,
                immunity_points=immunity_points,
                dmg_reduced=immunity_points,
                timestamp=get_timestamp(),
                line_number=line_number,
            )

        stripped_line = self._strip_chat_prefix(raw_line)
        if self._epic_dodge_marker in stripped_line:
            epic_dodge_match = patterns["epic_dodge"].search(stripped_line)
            if epic_dodge_match:
                return EpicDodgeEvent(
                    target=epic_dodge_match.group("target").strip(),
                    timestamp=get_timestamp(),
                    line_number=line_number,
                )

        attack_fast_data: Optional[Dict[str, Any]] = None
        if self._attack_marker in stripped_line:
            if self._target_concealed_marker in stripped_line:
                attack_fast_data, should_fallback = self._parse_attack_conceal_fast(stripped_line)
                attack_match = patterns["attack_conceal"].search(stripped_line) if should_fallback else None
            elif self._threat_roll_marker in stripped_line:
                attack_fast_data, should_fallback = self._parse_attack_threat_fast(stripped_line)
                attack_match = patterns["attack_with_threat"].search(stripped_line) if should_fallback else None
            elif self._attacker_miss_chance_marker in stripped_line:
                attack_match = patterns["attack_with_threat"].search(stripped_line)
            else:
                attack_fast_data, should_fallback = self._parse_attack_basic_fast(stripped_line)
                attack_match = patterns["attack"].search(stripped_line) if should_fallback else None
        else:
            attack_match = None

        if attack_fast_data is not None:
            attacker = attack_fast_data["attacker"]
            target = attack_fast_data["target"]
            outcome = attack_fast_data["outcome"]
            roll_str = str(attack_fast_data["roll"])
            total_str = str(attack_fast_data["total"])
            bonus_str = attack_fast_data["bonus"]
        elif attack_match:
            attacker = attack_match.group("attacker").strip()
            target = attack_match.group("target").strip()
            outcome = attack_match.group("outcome").lower() if "outcome" in attack_match.groupdict() else ""
            roll_str = attack_match.group("roll")
            total_str = attack_match.group("total")
            bonus_str = attack_match.group("bonus")
        else:
            attacker = ""
            target = ""
            outcome = ""
            roll_str = None
            total_str = None
            bonus_str = None

        if attack_fast_data is not None or attack_match:
            is_hit = "hit" in outcome
            is_crit = "critical" in outcome
            is_miss = "miss" in outcome or "parried" in outcome or "resisted" in outcome
            is_concealment = "attacker miss chance" in outcome
            if roll_str and total_str:
                roll = int(roll_str)
                total = int(total_str)
                bonus = int(bonus_str) if bonus_str else None
                if is_hit:
                    event_cls = AttackCriticalHitEvent if is_crit else AttackHitEvent
                    return event_cls(
                        attacker=attacker,
                        target=target,
                        roll=roll,
                        bonus=bonus,
                        total=total,
                        was_nat20=roll == 20,
                        is_concealment=is_concealment,
                        timestamp=get_timestamp(),
                        line_number=line_number,
                    )
                if is_miss:
                    return AttackMissEvent(
                        attacker=attacker,
                        target=target,
                        roll=roll,
                        bonus=bonus,
                        total=total,
                        was_nat1=roll == 1,
                        is_concealment=is_concealment,
                        timestamp=get_timestamp(),
                        line_number=line_number,
                    )

        if self._save_marker in stripped_line:
            save_match = patterns["save"].search(stripped_line)
            if save_match and save_match.group("bonus"):
                save_type = save_match.group("save_type").lower()
                save_key = "fort" if save_type in ("fort", "fortitude") else "ref" if save_type == "reflex" else "will"
                return SaveObservedEvent(
                    target=save_match.group("target").strip(),
                    save_type=save_key,
                    bonus=int(save_match.group("bonus")),
                    timestamp=get_timestamp(),
                    line_number=line_number,
                )

        return None
