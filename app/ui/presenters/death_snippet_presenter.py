"""Pure presenter helpers for death snippet rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ...constants import DAMAGE_TYPE_PALETTE
from ...parsed_events import DeathSnippetEvent


def _compile_damage_patterns() -> tuple[tuple[str, ...], tuple[tuple[str, re.Pattern[str]], ...], tuple[tuple[str, re.Pattern[str]], ...]]:
    """Compile keyword, pair, and standalone regex patterns from palette keys."""
    keys = tuple(DAMAGE_TYPE_PALETTE.keys())
    pair_patterns = tuple(
        (
            key,
            re.compile(
                rf"(?P<num>\d+)\s+(?P<dtype>{re.escape(key).replace(r'\\ ', r'\\s+')})\b",
                re.IGNORECASE,
            ),
        )
        for key in keys
    )
    type_patterns = tuple(
        (
            key,
            re.compile(rf"\b{re.escape(key).replace(r'\\ ', r'\\s+')}\b", re.IGNORECASE),
        )
        for key in keys
    )
    return keys, pair_patterns, type_patterns


@dataclass(frozen=True, slots=True)
class TextSpan:
    """One colored text segment inside a rendered line."""

    start: int
    end: int
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class PreparedLine:
    """One fully prepared line ready for widget rendering."""

    text: str
    spans: tuple[TextSpan, ...]


@dataclass(frozen=True, slots=True)
class PreparedDeathSnippetRender:
    """Prepared render payload for a death snippet event."""

    lines: tuple[PreparedLine, ...]
    sanitized_lines: tuple[str, ...]
    opponent_names: frozenset[str]
    killed_name: str
    killer_name: str


_DAMAGE_KEYWORDS, _PAIR_PATTERNS, _TYPE_PATTERNS = _compile_damage_patterns()
_DAMAGE_IMMUNITY_PREFIX = "Damage Immunity absorbs"
_SAVE_VS_MARKER = " Save vs. "
_DAMAGE_BREAKDOWN_PATTERN = re.compile(r"damages\s+[^:]+:\s*\d+\s*\((?P<breakdown>[^)]*)\)", re.IGNORECASE)
_IMMUNITY_OF_PATTERN = re.compile(r"\bof\s+(?P<dtype>.+?)\s*$", re.IGNORECASE)
_SAVE_VS_PATTERN = re.compile(r"\bSave\s+vs\.\s*(?P<dtype>.+?)\s*:", re.IGNORECASE)
_TIMESTAMP_PREFIX = re.compile(r"^\[[^]]+]\s*")
_ATTACKS_TARGET = re.compile(
    r"(?:Off Hand\s*:\s*)?"
    r"(?:[\w\s]+\s*:\s*)*"
    r"(?:Attack Of Opportunity\s*:\s*)?"
    r"(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:",
    re.IGNORECASE,
)
_DAMAGES_TARGET = re.compile(
    r"(?P<attacker>.+?)\s+damages\s+(?P<target>[^:]+?)\s*:",
    re.IGNORECASE,
)
_KILLED_TARGET = re.compile(
    r"(?P<killer>.+?)\s+killed\s+(?P<target>.+?)\s*$",
    re.IGNORECASE,
)
_CHAT_WINDOW_PREFIX = re.compile(r"^\[CHAT WINDOW TEXT]\s*")


def normalize_name(value: str) -> str:
    """Normalize user-entered or parsed names."""
    return " ".join(value.strip().split())


def sanitize_display_line(line: str) -> str:
    """Remove NWN chat boilerplate prefix for cleaner display."""
    return _CHAT_WINDOW_PREFIX.sub("", line)


def format_death_event_dropdown_value(timestamp: datetime | None, killer: str) -> str:
    """Build dropdown value text as HH:MM:SS plus original killer name."""
    killer_text = killer.strip() or "Unknown"
    if isinstance(timestamp, datetime):
        timestamp_text = timestamp.strftime("%H:%M:%S")
    else:
        timestamp_text = "--:--:--"
    return f"[{timestamp_text}] {killer_text}"


def prepare_display_lines_for_wrap_mode(
    lines: list[str],
    *,
    wrap_lines: bool,
    measure_text: Callable[[str], int] | None = None,
) -> list[str]:
    """Return lines adjusted for current wrap mode."""
    if wrap_lines or not lines or measure_text is None:
        return lines

    line_widths = [measure_text(line) for line in lines]
    max_width = max(line_widths, default=0)
    if max_width <= 0:
        return lines

    space_width = max(1, int(measure_text(" ")))
    padded_lines: list[str] = []
    for line, width in zip(lines, line_widths):
        deficit = max_width - width
        if deficit <= 0:
            padded_lines.append(line)
            continue
        padding_spaces = (deficit + space_width - 1) // space_width
        padded_lines.append(f"{line}{' ' * padding_spaces}")
    return padded_lines


def prepare_death_snippet_render(
    event: DeathSnippetEvent,
    *,
    wrap_lines: bool,
    measure_text: Callable[[str], int] | None = None,
) -> PreparedDeathSnippetRender:
    """Prepare all non-Tk render data for a death snippet event."""
    sanitized_lines = [sanitize_display_line(str(line)) for line in (event.lines or [])]
    display_lines = prepare_display_lines_for_wrap_mode(
        sanitized_lines,
        wrap_lines=wrap_lines,
        measure_text=measure_text,
    )
    killed_name = normalize_name(event.target)
    killer_name = normalize_name(event.killer)
    opponent_names = extract_opponent_names(
        sanitized_lines,
        killed_name=killed_name,
        killer_name=killer_name,
    )
    name_pattern_cache: dict[str, re.Pattern[str]] = {}
    prepared_lines = tuple(
        PreparedLine(
            text=line,
            spans=tuple(
                collect_render_spans(
                    line,
                    killed_name=killed_name,
                    opponent_names=opponent_names,
                    pattern_cache=name_pattern_cache,
                )
            ),
        )
        for line in display_lines
    )
    return PreparedDeathSnippetRender(
        lines=prepared_lines,
        sanitized_lines=tuple(sanitized_lines),
        opponent_names=frozenset(opponent_names),
        killed_name=killed_name,
        killer_name=killer_name,
    )


def strip_timestamp_prefix(line: str) -> str:
    """Remove leading timestamp prefix from a display line."""
    return _TIMESTAMP_PREFIX.sub("", line, count=1)


def line_may_have_damage_type(line: str) -> bool:
    """Fast gate before damage-type regex checks."""
    lowered = line.lower()
    return any(keyword in lowered for keyword in _DAMAGE_KEYWORDS)


def spans_overlap(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    """Return whether a span overlaps an existing occupied region."""
    for span_start, span_end in spans:
        if start < span_end and end > span_start:
            return True
    return False


def collect_color_spans(line: str) -> list[TextSpan]:
    """Collect damage color spans for one line using context-gated matching."""
    if not line:
        return []

    spans: list[TextSpan] = []
    line_has_keyword = line_may_have_damage_type(line)

    if _DAMAGE_IMMUNITY_PREFIX in line and line_has_keyword:
        immunity_match = _IMMUNITY_OF_PATTERN.search(line)
        if immunity_match:
            dtype_text = immunity_match.group("dtype")
            dtype_start = immunity_match.start("dtype")
            for color_key, pattern in _TYPE_PATTERNS:
                type_match = pattern.fullmatch(dtype_text.strip())
                if not type_match:
                    continue
                stripped = dtype_text.strip()
                local_offset = dtype_text.find(stripped)
                abs_start = dtype_start + local_offset
                abs_end = abs_start + len(stripped)
                spans.append(TextSpan(abs_start, abs_end, "damage", color_key))
                break

    if " damages " in line and "(" in line and ")" in line:
        breakdown_match = _DAMAGE_BREAKDOWN_PATTERN.search(line)
        if breakdown_match:
            breakdown = breakdown_match.group("breakdown")
            breakdown_start = breakdown_match.start("breakdown")
            for color_key, pattern in _PAIR_PATTERNS:
                for pair_match in pattern.finditer(breakdown):
                    num_start, num_end = pair_match.span("num")
                    type_start, type_end = pair_match.span("dtype")
                    spans.append(TextSpan(breakdown_start + num_start, breakdown_start + num_end, "damage", color_key))
                    spans.append(TextSpan(breakdown_start + type_start, breakdown_start + type_end, "damage", color_key))

    if _SAVE_VS_MARKER in line and line_has_keyword:
        save_match = _SAVE_VS_PATTERN.search(line)
        if save_match:
            dtype_text = save_match.group("dtype").strip()
            dtype_start = save_match.start("dtype")
            for color_key, pattern in _TYPE_PATTERNS:
                type_match = pattern.fullmatch(dtype_text)
                if not type_match:
                    continue
                spans.append(TextSpan(dtype_start, dtype_start + len(dtype_text), "damage", color_key))
                break

    unique_spans = {(span.start, span.end, span.kind, span.value) for span in spans}
    return [
        TextSpan(start, end, kind, value)
        for start, end, kind, value in sorted(unique_spans, key=lambda item: (item[0], item[1]))
    ]


def get_name_pattern(name: str, cache: dict[str, re.Pattern[str]]) -> re.Pattern[str]:
    """Get cached exact token-boundary regex for a name."""
    cached = cache.get(name)
    if cached is not None:
        return cached
    pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")
    cache[name] = pattern
    return pattern


def line_contains_any_name(line: str, names: set[str]) -> bool:
    """Fast substring gate before regex matching names."""
    if not names:
        return False
    lowered = line.lower()
    return any(name.lower() in lowered for name in names if name)


def collect_name_spans(
    line: str,
    *,
    killed_name: str,
    opponent_names: set[str],
    pattern_cache: dict[str, re.Pattern[str]] | None = None,
) -> list[TextSpan]:
    """Collect name color spans with killed/opponent precedence."""
    cache = pattern_cache if pattern_cache is not None else {}
    spans: list[TextSpan] = []

    if killed_name:
        killed_pattern = get_name_pattern(killed_name, cache)
        for match in killed_pattern.finditer(line):
            spans.append(TextSpan(match.start(), match.end(), "name", "killed"))

    occupied = [(span.start, span.end) for span in spans]
    if not line_contains_any_name(line, opponent_names):
        return spans

    for opponent in sorted(opponent_names, key=len, reverse=True):
        if not opponent:
            continue
        pattern = get_name_pattern(opponent, cache)
        for match in pattern.finditer(line):
            start, end = match.span(0)
            if spans_overlap(start, end, occupied):
                continue
            spans.append(TextSpan(start, end, "name", "opponent"))
            occupied.append((start, end))

    return sorted(spans, key=lambda item: (item.start, item.end))


def extract_opponent_names(
    lines: list[str],
    *,
    killed_name: str,
    killer_name: str,
) -> set[str]:
    """Extract opponents from lines that explicitly target the killed character."""
    opponents: set[str] = set()
    killed_fold = killed_name.casefold()

    killer = normalize_name(killer_name)
    if killer and killer.casefold() != killed_fold:
        opponents.add(killer)

    for line in lines:
        scan_line = strip_timestamp_prefix(line)
        for pattern, actor_group in (
            (_ATTACKS_TARGET, "attacker"),
            (_DAMAGES_TARGET, "attacker"),
            (_KILLED_TARGET, "killer"),
        ):
            match = pattern.search(scan_line)
            if not match:
                continue
            target = normalize_name(str(match.group("target")))
            if target.casefold() != killed_fold:
                continue
            actor = normalize_name(str(match.group(actor_group)))
            if actor and actor.casefold() != killed_fold:
                opponents.add(actor)

    return opponents


def collect_render_spans(
    line: str,
    *,
    killed_name: str,
    opponent_names: set[str],
    pattern_cache: dict[str, re.Pattern[str]] | None = None,
) -> list[TextSpan]:
    """Collect final render spans with name precedence over damage spans."""
    name_spans = collect_name_spans(
        line,
        killed_name=killed_name,
        opponent_names=opponent_names,
        pattern_cache=pattern_cache,
    )
    damage_spans = collect_color_spans(line)

    occupied_by_names = [(span.start, span.end) for span in name_spans]
    spans = list(name_spans)
    for span in damage_spans:
        if spans_overlap(span.start, span.end, occupied_by_names):
            continue
        spans.append(span)
    return sorted(spans, key=lambda item: (item.start, item.end))
