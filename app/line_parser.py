"""Pure per-line parser for NWN combat logs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, Optional

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


@dataclass(frozen=True, slots=True)
class _AttackParseResult:
    attacker: str
    target: str
    outcome: str
    roll: int | None
    bonus: int | None
    total: int | None


@dataclass(frozen=True, slots=True)
class _SaveParseResult:
    target: str
    save_key: str
    bonus: int


class LineParser:
    """Stateless single-line parser for combat log syntax."""

    DEATH_IDENTIFY_TOKEN = "wooparseme"
    WHISPER_MARKER = "[Whisper]"
    KILLED_MARKER = " killed "

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
                r"\*(?P<outcome>success|failed|failure)\*\s*:\s*"
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

        self._damage_marker = " damages "
        self._damage_immunity_marker = "Damage Immunity absorbs"
        self._attack_marker = " attacks "
        self._threat_roll_marker = "Threat Roll:"
        self._attacker_miss_chance_marker = "attacker miss chance:"
        self._target_concealed_marker = "target concealed:"
        self._save_marker = " Save"
        self._save_prefix_marker = "SAVE:"
        self._epic_dodge_marker = "Epic Dodge"

    @staticmethod
    def normalize_name(value: str) -> str:
        """Trim and normalize a character name string."""
        return " ".join(value.strip().split())

    @property
    def death_identify_token(self) -> str:
        """Return the configured whisper token used for auto-identification."""
        return self.DEATH_IDENTIFY_TOKEN

    def is_whisper_line(self, raw_line: str) -> bool:
        """Return True when a raw line could contain a death-identify whisper."""
        return self.WHISPER_MARKER in raw_line

    def is_killed_line(self, raw_line: str) -> bool:
        """Return True when a raw line could contain a killed-line marker."""
        return self.KILLED_MARKER in raw_line

    def match_chat_whisper(self, raw_line: str) -> Optional[re.Match[str]]:
        """Match a death-identify whisper line."""
        return self.patterns["chat_whisper"].search(raw_line)

    def match_killed_line(self, raw_line: str) -> Optional[re.Match[str]]:
        """Match a killed-line entry."""
        return self.patterns["killed"].search(raw_line)

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

        return self.build_timestamp_from_parts(parts, year=year)

    @staticmethod
    def build_timestamp_from_parts(
        parts: tuple[int, int, int, int, int],
        *,
        year: int,
    ) -> Optional[datetime]:
        """Build a timestamp from pre-parsed timestamp components."""

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
        token_count = len(tokens)
        index = 0
        while index < token_count:
            token = tokens[index]
            if not token.isdigit():
                index += 1
                continue

            amount = int(token)
            index += 1
            if index >= token_count:
                break

            if index + 1 == token_count or tokens[index + 1].isdigit():
                damage_types[tokens[index]] = amount
                index += 1
                continue

            type_start = index
            index += 1
            while index < token_count and not tokens[index].isdigit():
                index += 1
            damage_types[" ".join(tokens[type_start:index])] = amount

        return damage_types

    @staticmethod
    def _normalize_attack_attacker_name(raw_attacker: str) -> str:
        attacker = raw_attacker.strip()
        if " : " in attacker:
            attacker = attacker.rsplit(" : ", 1)[-1].strip()
        return attacker

    def _build_attack_parse_result(
        self,
        *,
        attacker: str,
        target: str,
        outcome: str,
        roll: int | None,
        bonus: int | None,
        total: int | None,
    ) -> _AttackParseResult:
        return _AttackParseResult(
            attacker=attacker,
            target=target,
            outcome=outcome,
            roll=roll,
            bonus=bonus,
            total=total,
        )

    def _parse_attack_threat_fast(self, s: str) -> tuple[Optional[_AttackParseResult], bool]:
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

        return self._build_attack_parse_result(
            attacker=attacker,
            target=target,
            outcome=outcome,
            roll=int(roll_str),
            bonus=int(bonus_str),
            total=int(total_tail[:total_end]),
        ), False

    def _parse_attack_basic_fast(self, s: str) -> tuple[Optional[_AttackParseResult], bool]:
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
            return self._build_attack_parse_result(
                attacker=attacker,
                target=target,
                outcome=outcome,
                roll=None,
                bonus=None,
                total=None,
            ), False
        if tail.startswith(":"):
            tail = tail[1:].strip()
        if not tail:
            return self._build_attack_parse_result(
                attacker=attacker,
                target=target,
                outcome=outcome,
                roll=None,
                bonus=None,
                total=None,
            ), False

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

        return self._build_attack_parse_result(
            attacker=attacker,
            target=target,
            outcome=outcome,
            roll=int(roll_str),
            bonus=int(bonus_str),
            total=int(total_str),
        ), False

    def _parse_attack_conceal_fast(self, s: str) -> tuple[Optional[_AttackParseResult], bool]:
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

            return self._build_attack_parse_result(
                attacker=attacker,
                target=target,
                outcome=outcome,
                roll=roll,
                bonus=bonus,
                total=total,
            ), False
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

    def _parse_save_fast(self, stripped_line: str) -> Optional[_SaveParseResult]:
        if self._save_marker not in stripped_line:
            return None

        working = stripped_line.strip()
        if not working:
            return None

        if working[: len(self._save_prefix_marker)].upper() == self._save_prefix_marker:
            working = working[len(self._save_prefix_marker):].lstrip()
            if not working:
                return None

        marker_specs = (
            (" : Fortitude Save", "fort"),
            (" : Fort Save", "fort"),
            (" : Reflex Save", "ref"),
            (" : Will Save", "will"),
        )
        lowered = working.lower()
        target = ""
        save_key = ""
        rest = ""
        for marker, candidate_save_key in marker_specs:
            marker_idx = lowered.find(marker.lower())
            if marker_idx < 0:
                continue
            target = working[:marker_idx].strip()
            rest = working[marker_idx + len(marker):].strip()
            save_key = candidate_save_key
            break

        if not target or not rest or not save_key:
            return None

        star_start = rest.find("*")
        if star_start < 0:
            return None

        star_end = rest.find("*", star_start + 1)
        if star_end < 0:
            return None

        outcome = rest[star_start + 1:star_end].strip().lower()
        if outcome not in {"success", "failed", "failure"}:
            return None

        tail = rest[star_end + 1:].strip()
        if tail.startswith(":"):
            tail = tail[1:].strip()
        if not tail.startswith("("):
            return None

        expr_end = tail.find(")")
        if expr_end < 0:
            return None

        expr = tail[1:expr_end]
        expr_lower = expr.lower()
        dc_idx = expr_lower.find("vs. dc:")
        if dc_idx < 0:
            return None

        roll_bonus = expr[:dc_idx].strip()
        if "=" in roll_bonus:
            roll_bonus = roll_bonus.split("=", 1)[0].strip()

        plus_idx = roll_bonus.find("+")
        if plus_idx < 0:
            return None

        bonus_str = roll_bonus[plus_idx + 1:].strip()
        if not bonus_str:
            return None

        try:
            bonus = int(bonus_str)
        except ValueError:
            return None

        return _SaveParseResult(
            target=target.strip(" :"),
            save_key=save_key,
            bonus=bonus,
        )

    def _parse_damage_event(
        self,
        raw_line: str,
        *,
        line_number: int,
        get_timestamp: Callable[[], datetime],
    ) -> Optional[DamageDealtEvent]:
        if self._damage_marker not in raw_line:
            return None

        damage_match = self.patterns["damage_dealt"].search(raw_line)
        if not damage_match:
            return None

        attacker = damage_match.group(1).strip()
        target = damage_match.group(2).strip()
        total_damage = int(damage_match.group(3))
        damage_types = self.parse_damage_breakdown(damage_match.group(4))
        return DamageDealtEvent(
            get_timestamp(),
            line_number,
            attacker,
            target,
            total_damage,
            damage_types,
        )

    def _parse_immunity_event(
        self,
        raw_line: str,
        *,
        line_number: int,
        get_timestamp: Callable[[], datetime],
    ) -> Optional[ImmunityObservedEvent]:
        if self._damage_immunity_marker not in raw_line:
            return None
        if not self.parse_immunity:
            return None

        immunity_match = self.patterns["damage_immunity"].search(raw_line)
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

    def _parse_epic_dodge_event(
        self,
        stripped_line: str,
        *,
        line_number: int,
        get_timestamp: Callable[[], datetime],
    ) -> Optional[EpicDodgeEvent]:
        if self._epic_dodge_marker not in stripped_line:
            return None

        epic_dodge_match = self.patterns["epic_dodge"].search(stripped_line)
        if not epic_dodge_match:
            return None

        return EpicDodgeEvent(
            target=epic_dodge_match.group("target").strip(),
            timestamp=get_timestamp(),
            line_number=line_number,
        )

    def _parse_attack_match(self, stripped_line: str) -> Optional[_AttackParseResult]:
        if self._attack_marker not in stripped_line:
            return None

        attack_fast_data: Optional[_AttackParseResult]
        attack_match: Optional[re.Match[str]]
        if self._target_concealed_marker in stripped_line:
            attack_fast_data, should_fallback = self._parse_attack_conceal_fast(stripped_line)
            attack_match = self.patterns["attack_conceal"].search(stripped_line) if should_fallback else None
        elif self._threat_roll_marker in stripped_line:
            attack_fast_data, should_fallback = self._parse_attack_threat_fast(stripped_line)
            attack_match = self.patterns["attack_with_threat"].search(stripped_line) if should_fallback else None
        elif self._attacker_miss_chance_marker in stripped_line:
            attack_fast_data = None
            attack_match = self.patterns["attack_with_threat"].search(stripped_line)
        else:
            attack_fast_data, should_fallback = self._parse_attack_basic_fast(stripped_line)
            attack_match = self.patterns["attack"].search(stripped_line) if should_fallback else None

        if attack_fast_data is not None:
            return attack_fast_data
        if not attack_match:
            return None

        return self._build_attack_parse_result(
            attacker=attack_match.group("attacker").strip(),
            target=attack_match.group("target").strip(),
            outcome=attack_match.group("outcome").lower() if "outcome" in attack_match.groupdict() else "",
            roll=int(attack_match.group("roll")) if attack_match.group("roll") is not None else None,
            bonus=int(attack_match.group("bonus")) if attack_match.group("bonus") is not None else None,
            total=int(attack_match.group("total")) if attack_match.group("total") is not None else None,
        )

    def _build_attack_event(
        self,
        attack_data: _AttackParseResult,
        *,
        line_number: int,
        get_timestamp: Callable[[], datetime],
    ) -> Optional[AttackHitEvent | AttackCriticalHitEvent | AttackMissEvent]:
        if attack_data.roll is None or attack_data.total is None:
            return None

        outcome = attack_data.outcome
        is_hit = "hit" in outcome
        is_crit = "critical" in outcome
        is_miss = "miss" in outcome or "parried" in outcome or "resisted" in outcome
        is_concealment = "attacker miss chance" in outcome
        if is_hit:
            event_cls = AttackCriticalHitEvent if is_crit else AttackHitEvent
            return event_cls(
                attacker=attack_data.attacker,
                target=attack_data.target,
                roll=attack_data.roll,
                bonus=attack_data.bonus,
                total=attack_data.total,
                was_nat20=attack_data.roll == 20,
                is_concealment=is_concealment,
                timestamp=get_timestamp(),
                line_number=line_number,
            )
        if is_miss:
            return AttackMissEvent(
                attacker=attack_data.attacker,
                target=attack_data.target,
                roll=attack_data.roll,
                bonus=attack_data.bonus,
                total=attack_data.total,
                was_nat1=attack_data.roll == 1,
                is_concealment=is_concealment,
                timestamp=get_timestamp(),
                line_number=line_number,
            )
        return None

    def _parse_attack_event(
        self,
        stripped_line: str,
        *,
        line_number: int,
        get_timestamp: Callable[[], datetime],
    ) -> Optional[AttackHitEvent | AttackCriticalHitEvent | AttackMissEvent]:
        attack_data = self._parse_attack_match(stripped_line)
        if attack_data is None:
            return None
        return self._build_attack_event(
            attack_data,
            line_number=line_number,
            get_timestamp=get_timestamp,
        )

    def _parse_save_event(
        self,
        stripped_line: str,
        *,
        line_number: int,
        get_timestamp: Callable[[], datetime],
    ) -> Optional[SaveObservedEvent]:
        if self._save_marker not in stripped_line:
            return None

        save_fast = self._parse_save_fast(stripped_line)
        if save_fast is not None:
            return SaveObservedEvent(
                target=save_fast.target,
                save_type=save_fast.save_key,
                bonus=save_fast.bonus,
                timestamp=get_timestamp(),
                line_number=line_number,
            )

        save_match = self.patterns["save"].search(stripped_line)
        if not save_match or save_match.group("bonus") is None:
            return None

        save_type = save_match.group("save_type").lower()
        save_key = "fort" if save_type in ("fort", "fortitude") else "ref" if save_type == "reflex" else "will"
        return SaveObservedEvent(
            target=save_match.group("target").strip(),
            save_type=save_key,
            bonus=int(save_match.group("bonus")),
            timestamp=get_timestamp(),
            line_number=line_number,
        )

    def parse_line(
        self,
        raw_line: str,
        *,
        line_number: int,
        get_timestamp: Callable[[], datetime],
    ) -> Optional[ParsedEvent]:
        """Parse a non-empty raw line without session history state."""
        damage_event = self._parse_damage_event(
            raw_line,
            line_number=line_number,
            get_timestamp=get_timestamp,
        )
        if damage_event is not None:
            return damage_event

        immunity_event = self._parse_immunity_event(
            raw_line,
            line_number=line_number,
            get_timestamp=get_timestamp,
        )
        if immunity_event is not None:
            return immunity_event

        stripped_line = self._strip_chat_prefix(raw_line)
        epic_dodge_event = self._parse_epic_dodge_event(
            stripped_line,
            line_number=line_number,
            get_timestamp=get_timestamp,
        )
        if epic_dodge_event is not None:
            return epic_dodge_event

        attack_event = self._parse_attack_event(
            stripped_line,
            line_number=line_number,
            get_timestamp=get_timestamp,
        )
        if attack_event is not None:
            return attack_event

        save_event = self._parse_save_event(
            stripped_line,
            line_number=line_number,
            get_timestamp=get_timestamp,
        )
        if save_event is not None:
            return save_event

        return None
