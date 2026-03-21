"""Compatibility facade for the staged parser split."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from .line_parser import LineParser
from .parsed_events import ParsedEvent
from .parser_session import ParserSession


class LogParser:
    """Compatibility facade over ``ParserSession`` and ``LineParser``."""

    DEFAULT_DEATH_FALLBACK_LINE = ParserSession.DEFAULT_DEATH_FALLBACK_LINE
    DEATH_IDENTIFY_TOKEN = LineParser.DEATH_IDENTIFY_TOKEN

    def __init__(
        self,
        player_name: Optional[str] = None,
        parse_immunity: bool = True,
        max_recent_log_lines: int = 20000,
    ) -> None:
        self._session = ParserSession(
            player_name=player_name,
            parse_immunity=parse_immunity,
            max_recent_log_lines=max_recent_log_lines,
        )

    @property
    def player_name(self) -> Optional[str]:
        return self._session.player_name

    @property
    def parse_immunity(self) -> bool:
        return self._session.parse_immunity

    @parse_immunity.setter
    def parse_immunity(self, value: bool) -> None:
        self._session.parse_immunity = bool(value)

    @property
    def death_character_name(self) -> str:
        return self._session.death_character_name

    @property
    def death_fallback_line(self) -> str:
        return self._session.death_fallback_line

    def parse_damage_breakdown(self, breakdown_str: str) -> Dict[str, int]:
        return self._session.line_parser.parse_damage_breakdown(breakdown_str)

    def set_death_character_name(self, name: str) -> None:
        self._session.set_death_character_name(name)

    def set_death_fallback_line(self, line: str) -> None:
        self._session.set_death_fallback_line(line)

    def extract_timestamp_from_line(self, line: str) -> Optional[datetime]:
        return self._session.extract_timestamp_from_line(line)

    def parse_line(self, line: str) -> Optional[ParsedEvent]:
        return self._session.parse_line(line)


__all__ = ["LineParser", "LogParser", "ParserSession"]
