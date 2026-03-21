"""Unit tests for pure death snippet presenter helpers."""

from datetime import datetime

from app.parsed_events import DeathSnippetEvent
from app.ui.presenters.death_snippet_presenter import (
    collect_color_spans,
    collect_render_spans,
    extract_opponent_names,
    prepare_death_snippet_render,
    prepare_display_lines_for_wrap_mode,
    sanitize_display_line,
)


def _event(*, lines: list[str], killer: str = "HYDROXIS", target: str = "Woo Wildrock") -> DeathSnippetEvent:
    return DeathSnippetEvent(
        timestamp=datetime(2026, 1, 9, 14, 30, 0),
        killer=killer,
        lines=lines,
        target=target,
        line_number=None,
    )


def _fake_measure(text: str) -> int:
    return len(text) * 8


def test_sanitize_display_line_removes_chat_window_prefix() -> None:
    line = "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"
    sanitized = sanitize_display_line(line)
    assert sanitized == "[Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"


def test_sanitize_display_line_leaves_non_prefixed_line_unchanged() -> None:
    line = "[Tue Jan 13 19:59:36] HYDROXYS killed Woo Wildrock"
    sanitized = sanitize_display_line(line)
    assert sanitized == line


def test_collect_color_spans_colors_adjacent_pairs() -> None:
    line = "BIOLLANTE damages Woo Whirlwind: 99 (27 Positive Energy 50 Fire 22 Negative Energy)"
    spans = collect_color_spans(line)

    colored_tokens = [line[span.start:span.end] for span in spans]
    assert "27" in colored_tokens
    assert "Positive Energy" in colored_tokens
    assert "50" in colored_tokens
    assert "Fire" in colored_tokens
    assert "22" in colored_tokens
    assert "Negative Energy" in colored_tokens


def test_collect_color_spans_does_not_color_non_adjacent_immunity_number() -> None:
    line = "Damage Immunity absorbs 10 point(s) of Fire"
    spans = collect_color_spans(line)

    colored_tokens = [line[span.start:span.end] for span in spans]
    assert "Fire" in colored_tokens
    assert "10" not in colored_tokens


def test_collect_color_spans_colors_save_vs_damage_type() -> None:
    line = "Woo Whirlwind : Fortitude Save vs. Acid : *success* : (20 + 50 = 70 vs. DC: 52)"
    spans = collect_color_spans(line)
    colored_tokens = [line[span.start:span.end] for span in spans]
    assert "Acid" in colored_tokens


def test_collect_color_spans_skips_spell_resist_spell_names() -> None:
    line = "SPELL RESIST: Woo Whirlwind attempts to resist: Acid Fog - Result: FAILED"
    spans = collect_color_spans(line)
    colored_tokens = [line[span.start:span.end] for span in spans]
    assert "Acid" not in colored_tokens


def test_collect_color_spans_skips_wall_of_fire_spell_name() -> None:
    line = "SPELL RESIST: Woo Whirlwind attempts to resist: Wall of Fire - Result: FAILED"
    spans = collect_color_spans(line)
    colored_tokens = [line[span.start:span.end] for span in spans]
    assert "Fire" not in colored_tokens


def test_extract_opponent_names_from_hostile_lines_targeting_killed() -> None:
    lines = [
        "[Wed Jan 09 14:30:00] Ash-Tusk Clan Sniper attacks Woo Whirlwind : *hit* : (12 + 56 = 68)",
        "[Wed Jan 09 14:30:01] GENERAL KORGAN damages Woo Whirlwind: 40 (0 Physical 4 Divine 36 Electrical 0 Fire)",
        "[Wed Jan 09 14:30:02] HYDROXIS killed Woo Whirlwind",
        "[Wed Jan 09 14:30:03] GENERAL KORGAN casts unknown spell",
    ]

    opponents = extract_opponent_names(
        lines,
        killed_name="Woo Whirlwind",
        killer_name="HYDROXIS",
    )

    assert "HYDROXIS" in opponents
    assert "Ash-Tusk Clan Sniper" in opponents
    assert "GENERAL KORGAN" in opponents


def test_collect_render_spans_gives_killed_name_precedence_over_opponent_spans() -> None:
    line = "Woo Whirlwind attacks Woo Whirlwind : *hit*"
    spans = collect_render_spans(
        line,
        killed_name="Woo Whirlwind",
        opponent_names={"Woo Whirlwind"},
    )

    assert len(spans) == 2
    assert all(span.kind == "name" for span in spans)
    assert all(span.value == "killed" for span in spans)


def test_prepare_display_lines_for_wrap_mode_no_wrap_pads_shorter_lines() -> None:
    prepared = prepare_display_lines_for_wrap_mode(
        ["abcd", "ab"],
        wrap_lines=False,
        measure_text=_fake_measure,
    )

    assert prepared[0] == "abcd"
    assert prepared[1] == "ab  "


def test_prepare_display_lines_for_wrap_mode_wrap_on_keeps_lines_unchanged() -> None:
    prepared = prepare_display_lines_for_wrap_mode(
        ["abcd", "ab"],
        wrap_lines=True,
        measure_text=_fake_measure,
    )

    assert prepared == ["abcd", "ab"]


def test_prepare_death_snippet_render_builds_sanitized_lines_opponents_and_spans() -> None:
    prepared = prepare_death_snippet_render(
        _event(lines=[
            "[CHAT WINDOW TEXT] [t] Ash-Tusk Clan Sniper attacks Woo Whirlwind : *hit* : (12 + 56 = 68)",
            "[CHAT WINDOW TEXT] [t] GENERAL KORGAN damages Woo Whirlwind: 40 (0 Physical 4 Divine 36 Electrical 0 Fire)",
            "[CHAT WINDOW TEXT] [t] HYDROXIS killed Woo Whirlwind",
        ], target="Woo Whirlwind"),
        wrap_lines=False,
        measure_text=_fake_measure,
    )

    assert prepared.sanitized_lines[0].startswith("[t] Ash-Tusk Clan Sniper")
    assert "HYDROXIS" in prepared.opponent_names
    assert "Ash-Tusk Clan Sniper" in prepared.opponent_names
    assert "GENERAL KORGAN" in prepared.opponent_names
    assert any(span.value == "killed" for span in prepared.lines[0].spans)
    assert any(span.kind == "damage" and span.value == "electrical" for span in prepared.lines[1].spans)
