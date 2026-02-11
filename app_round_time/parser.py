"""Minimal log parser for attack lines and timestamps."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .models import AttackEvent


class LogParser:
    def __init__(self) -> None:
        self.timestamp_pattern = re.compile(r"\[CHAT WINDOW TEXT\] \[([^]]+)]")

        self.patterns = {
            "attack": re.compile(
                r"(?:Off Hand\s*:\s*)?"
                r"(?:[\w\s]+\s*:\s*)*"
                r"(?:Attack Of Opportunity\s*:\s*)?"
                r"(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*"
                r"\*(?P<outcome>hit|miss|critical hit|parried|resisted)\*\s*"
                r"(?:\s*:\s*\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)\))?",
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
        }

    def extract_timestamp_from_line(self, line: str) -> Optional[datetime]:
        match = self.timestamp_pattern.search(line)
        if not match:
            return None

        timestamp_str = match.group(1)
        parts = timestamp_str.split()
        if len(parts) < 4:
            return None

        months = {
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

        month_str = parts[1]
        if month_str not in months:
            return None

        try:
            day = int(parts[2])
            time_parts = parts[3].split(":")
            if len(time_parts) != 3:
                return None
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            second = int(time_parts[2])
            current_year = datetime.now().year
            return datetime(current_year, months[month_str], day, hour, minute, second)
        except Exception:
            return None

    def parse_line(self, line: str) -> Optional[AttackEvent]:
        if not line.strip():
            return None

        timestamp = self.extract_timestamp_from_line(line)

        stripped_line = line
        if "[CHAT WINDOW TEXT]" in line:
            stripped_line = re.sub(r"^\[CHAT WINDOW TEXT\]\s*\[[^]]+]\s*", "", line)

        attack_match = self.patterns["attack_with_threat"].search(stripped_line)
        if not attack_match:
            attack_match = self.patterns["attack_conceal"].search(stripped_line)
        if not attack_match:
            attack_match = self.patterns["attack"].search(stripped_line)

        if not attack_match:
            return None

        attacker = attack_match.group("attacker").strip()
        target = attack_match.group("target").strip()
        outcome = attack_match.group("outcome").lower() if "outcome" in attack_match.groupdict() else ""

        return AttackEvent(
            attacker=attacker,
            target=target,
            outcome=outcome,
            log_timestamp=timestamp,
        )
