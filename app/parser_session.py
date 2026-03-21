"""Stateful parser-session logic for death correlation and year inference."""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime
from typing import Deque, Dict, Iterable, Iterator, Optional, Pattern

from .line_parser import LineParser
from .parsed_events import DeathCharacterIdentifiedEvent, DeathSnippetEvent, ParsedEvent


class ParserSession:
    """Stateful parser session built on top of ``LineParser``."""

    DEFAULT_DEATH_FALLBACK_LINE = "Your God refuses to hear your prayers!"

    def __init__(
        self,
        *,
        line_parser: Optional[LineParser] = None,
        player_name: Optional[str] = None,
        parse_immunity: bool = True,
        max_recent_log_lines: int = 20000,
        anchor_year: Optional[int] = None,
    ) -> None:
        self.line_parser = line_parser or LineParser(
            player_name=player_name,
            parse_immunity=parse_immunity,
        )
        self._line_number = 0
        self._anchor_year = datetime.now().year if anchor_year is None else anchor_year
        self._last_timestamp_year: Optional[int] = None
        self._last_timestamp_month: Optional[int] = None

        self.death_lookup_killed_lookback_lines = 500
        self.death_snippet_max_lines = 100
        self.recent_log_lines: Deque[str] = deque(maxlen=max(1, int(max_recent_log_lines)))
        self._name_token_pattern_cache: Dict[str, Pattern[str]] = {}
        self.death_character_name = ""
        self._death_character_name_normalized = ""
        self.death_fallback_line = self.DEFAULT_DEATH_FALLBACK_LINE
        self._death_fallback_pattern: Optional[Pattern[str]] = self._compile_fallback_line_pattern(
            self.death_fallback_line
        )

    @property
    def player_name(self) -> Optional[str]:
        return self.line_parser.player_name

    @property
    def parse_immunity(self) -> bool:
        return self.line_parser.parse_immunity

    @parse_immunity.setter
    def parse_immunity(self, value: bool) -> None:
        self.line_parser.parse_immunity = bool(value)

    def _resolve_year(self, month: int) -> int:
        if self._last_timestamp_year is None:
            year = self._anchor_year
        else:
            year = self._last_timestamp_year
            if self._last_timestamp_month == 12 and month == 1:
                year += 1

        self._last_timestamp_year = year
        self._last_timestamp_month = month
        return year

    def extract_timestamp_from_line(self, line: str) -> Optional[datetime]:
        """Resolve a timestamp using session-relative year inference."""
        parts = self.line_parser.extract_timestamp_parts(line)
        if parts is None:
            return None

        month, _day, _hour, _minute, _second = parts
        year = self._resolve_year(month)
        return self.line_parser.build_timestamp(line, year=year)

    def set_death_character_name(self, name: str) -> None:
        normalized = self.line_parser.normalize_name(name)
        self.death_character_name = normalized
        self._death_character_name_normalized = normalized

    @staticmethod
    def _compile_fallback_line_pattern(value: str) -> Optional[Pattern[str]]:
        normalized = value.strip()
        if not normalized:
            return None
        return re.compile(rf"\[CHAT WINDOW TEXT]\s*\[.*?]\s*{re.escape(normalized)}\s*$")

    def set_death_fallback_line(self, line: str) -> None:
        self.death_fallback_line = line.strip()
        self._death_fallback_pattern = self._compile_fallback_line_pattern(self.death_fallback_line)

    def _get_name_token_pattern(self, character_name: str) -> Pattern[str]:
        cached = self._name_token_pattern_cache.get(character_name)
        if cached is not None:
            return cached

        pattern = re.compile(rf"(?<!\w){re.escape(character_name)}(?!\w)")
        self._name_token_pattern_cache[character_name] = pattern
        return pattern

    def _collect_death_snippet_lines(
        self,
        *,
        candidates_reversed: Iterable[str],
        target_name: str,
        trigger_line: Optional[str] = None,
    ) -> Optional[list[str]]:
        if not target_name:
            return None

        name_pattern = self._get_name_token_pattern(target_name)
        snippet_reversed = []
        for candidate in candidates_reversed:
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

    def _iter_recent_log_lines_reversed(self, skip_latest: int = 0) -> Iterator[str]:
        lines = iter(reversed(self.recent_log_lines))
        for _ in range(max(0, skip_latest)):
            if next(lines, None) is None:
                return
        for candidate in lines:
            yield candidate

    def _build_death_snippet_event_from_fallback(
        self,
        fallback_line: str,
        timestamp: datetime,
        line_number: int,
    ) -> Optional[DeathSnippetEvent]:
        if len(self.recent_log_lines) < 2:
            return None

        killed_match = None
        scanned = 0
        for candidate in self._iter_recent_log_lines_reversed(skip_latest=1):
            if scanned >= self.death_lookup_killed_lookback_lines:
                break
            scanned += 1
            match = self.line_parser.match_killed_line(candidate)
            if match:
                killed_match = match
                break

        if not killed_match:
            return None

        dead_target = killed_match.group("target").strip()
        killer = killed_match.group("killer").strip()
        if not dead_target:
            return None

        snippet_lines = self._collect_death_snippet_lines(
            candidates_reversed=self._iter_recent_log_lines_reversed(skip_latest=1),
            target_name=dead_target,
            trigger_line=fallback_line,
        )
        if not snippet_lines:
            return None

        return DeathSnippetEvent(
            target=dead_target,
            killer=killer,
            lines=snippet_lines,
            timestamp=timestamp,
            line_number=line_number,
        )

    def _build_death_snippet_event_from_killed_match(
        self,
        *,
        killer: str,
        target: str,
        timestamp: datetime,
        line_number: int,
    ) -> Optional[DeathSnippetEvent]:
        snippet_lines = self._collect_death_snippet_lines(
            candidates_reversed=reversed(self.recent_log_lines),
            target_name=target,
        )
        if not snippet_lines:
            return None

        return DeathSnippetEvent(
            target=target,
            killer=killer,
            lines=snippet_lines,
            timestamp=timestamp,
            line_number=line_number,
        )

    def parse_line(self, line: str) -> Optional[ParsedEvent]:
        if not line.strip():
            return None

        raw_line = line.rstrip("\r\n")
        self._line_number += 1
        line_number = self._line_number
        self.recent_log_lines.append(raw_line)
        timestamp: Optional[datetime] = None

        def get_timestamp() -> datetime:
            nonlocal timestamp
            if timestamp is None:
                timestamp = self.extract_timestamp_from_line(raw_line)
                if not timestamp:
                    timestamp = datetime.now()
            return timestamp

        if self.line_parser.is_whisper_line(raw_line):
            whisper_match = self.line_parser.match_chat_whisper(raw_line)
            if whisper_match:
                message = str(whisper_match.group("message")).strip()
                if message.casefold() == self.line_parser.death_identify_token:
                    speaker = self.line_parser.normalize_name(str(whisper_match.group("speaker")))
                    if speaker:
                        self.set_death_character_name(speaker)
                        return DeathCharacterIdentifiedEvent(
                            character_name=speaker,
                            timestamp=get_timestamp(),
                            line_number=line_number,
                        )

        if self.line_parser.is_killed_line(raw_line) and self._death_character_name_normalized:
            killed_match = self.line_parser.match_killed_line(raw_line)
            if killed_match:
                dead_target = self.line_parser.normalize_name(str(killed_match.group("target")))
                if dead_target == self._death_character_name_normalized:
                    killer = self.line_parser.normalize_name(str(killed_match.group("killer")))
                    death_event = self._build_death_snippet_event_from_killed_match(
                        killer=killer,
                        target=dead_target,
                        timestamp=get_timestamp(),
                        line_number=line_number,
                    )
                    if death_event:
                        return death_event

        if (not self._death_character_name_normalized) and self._death_fallback_pattern:
            if self._death_fallback_pattern.search(raw_line):
                death_event = self._build_death_snippet_event_from_fallback(
                    raw_line,
                    get_timestamp(),
                    line_number,
                )
                if death_event:
                    return death_event

        return self.line_parser.parse_line(
            raw_line,
            line_number=line_number,
            get_timestamp=get_timestamp,
        )
