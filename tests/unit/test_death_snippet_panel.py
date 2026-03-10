"""Unit tests for DeathSnippetPanel behavior."""

from datetime import datetime

from app.ui.widgets.death_snippet_panel import DeathSnippetPanel


class _FakeText:
    def __init__(self, content: str = "") -> None:
        self.content = content
        self.seen = False
        self.tag_configs = {}
        self.inserts = []
        self.config = {}
        self.yview_start = 0.0
        self.top_index = "1.0"

    def delete(self, *_args) -> None:
        self.content = ""

    def insert(self, index, text: str, *tags) -> None:
        tag = tags[0] if tags else None
        self.inserts.append((index, text, tag))
        if index == "1.0":
            self.content = text
        else:
            self.content += text

    def tag_configure(self, tag: str, **kwargs) -> None:
        self.tag_configs[tag] = kwargs

    def get(self, *_args) -> str:
        return self.content

    def see(self, *_args) -> None:
        self.seen = True

    def configure(self, **kwargs) -> None:
        self.config.update(kwargs)

    def xview(self, *_args) -> None:
        return None

    def yview(self, *_args):
        if _args:
            self.top_index = str(_args[0])
            return None
        return (self.yview_start, min(1.0, self.yview_start + 0.2))

    def yview_moveto(self, fraction: float) -> None:
        self.yview_start = float(fraction)

    def index(self, expr: str) -> str:
        if expr == "@0,0":
            return self.top_index
        return "1.0"


class _FakeBoolVar:
    def __init__(self, value: bool) -> None:
        self.value = bool(value)

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = bool(value)


class _FakeStringVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _FakeScrollbar:
    def __init__(self) -> None:
        self.mapped = False
        self.command = None
        self.manager = ""
    def set(self, *_args) -> None:
        return None

    def config(self, **kwargs) -> None:
        if "command" in kwargs:
            self.command = kwargs["command"]

    def winfo_ismapped(self) -> bool:
        return self.mapped

    def winfo_manager(self) -> str:
        return self.manager

    def pack(self, **_kwargs) -> None:
        self.mapped = True
        self.manager = "pack"

    def pack_forget(self) -> None:
        self.mapped = False
        self.manager = ""

    def grid(self, **_kwargs) -> None:
        self.mapped = True
        self.manager = "grid"

    def grid_remove(self) -> None:
        self.mapped = False
        self.manager = ""


class _FakeCombo:
    def __init__(self) -> None:
        self.values = ()
        self.state = "disabled"
        self.selected_index = -1
        self.value = ""

    def __setitem__(self, key: str, value) -> None:
        if key == "values":
            self.values = tuple(value)

    def configure(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]

    def set(self, value: str) -> None:
        self.value = value
        if value in self.values:
            self.selected_index = self.values.index(value)
        else:
            self.selected_index = -1

    def get(self) -> str:
        if 0 <= self.selected_index < len(self.values):
            return self.values[self.selected_index]
        return self.value

    def current(self, index=None):
        if index is None:
            return self.selected_index
        self.selected_index = int(index)
        if 0 <= self.selected_index < len(self.values):
            self.value = self.values[self.selected_index]

    def cget(self, key: str):
        if key == "values":
            return self.values
        raise KeyError(key)


class TestDeathSnippetPanel:
    """Test suite for DeathSnippetPanel helper behavior."""

    def _make_panel(self) -> DeathSnippetPanel:
        class _FakeVar:
            def __init__(self, combo: _FakeCombo) -> None:
                self.value = ""
                self.combo = combo

            def set(self, value: str) -> None:
                self.value = value
                self.combo.value = value

        panel = DeathSnippetPanel.__new__(DeathSnippetPanel)
        panel.text = _FakeText(DeathSnippetPanel.EMPTY_TEXT_PLACEHOLDER)
        panel.killed_by_combo = _FakeCombo()
        panel.killed_by_var = _FakeVar(panel.killed_by_combo)
        panel.death_events = []
        panel._event_sequence = 0
        panel._text_tags_by_color = {}
        panel._last_render_key = None
        panel._name_pattern_cache = {}
        panel.line_wrap_var = _FakeBoolVar(True)
        panel.hscroll = _FakeScrollbar()
        panel.character_name_var = _FakeStringVar("")
        panel._character_hint_active = False
        panel._suppress_identity_callbacks = False
        panel._on_character_name_changed = None
        panel._character_entry_foreground = None
        panel._set_character_entry_foreground = (
            lambda color: setattr(panel, "_character_entry_foreground", color)
        )
        return panel

    @staticmethod
    def _make_fake_font(char_px: int = 8) -> object:
        class _FakeFont:
            def __init__(self, px: int) -> None:
                self.px = px

            def measure(self, text: str) -> int:
                return len(text) * self.px

        return _FakeFont(char_px)

    def test_sanitize_display_line_removes_chat_window_prefix(self) -> None:
        line = "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"
        sanitized = DeathSnippetPanel._sanitize_display_line(line)
        assert sanitized == "[Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"

    def test_sanitize_display_line_leaves_non_prefixed_line_unchanged(self) -> None:
        line = "[Tue Jan 13 19:59:36] HYDROXYS killed Woo Wildrock"
        sanitized = DeathSnippetPanel._sanitize_display_line(line)
        assert sanitized == line

    def test_add_death_event_auto_selects_newest_and_preserves_killer_case(self) -> None:
        panel = self._make_panel()

        older = {
            "timestamp": datetime(2026, 1, 9, 14, 30, 0),
            "killer": "hydroXis",
            "lines": ["[CHAT WINDOW TEXT] [t] hydroXis killed Woo Wildrock"],
            "target": "Woo Wildrock",
        }
        newer = {
            "timestamp": datetime(2026, 1, 9, 14, 55, 23),
            "killer": "HYDROXIS",
            "lines": ["[CHAT WINDOW TEXT] [t] HYDROXIS killed Woo Wildrock"],
            "target": "Woo Wildrock",
        }

        panel.add_death_event(older)
        panel.add_death_event(newer)

        assert panel.killed_by_combo.values == (
            "[14:55:23] HYDROXIS",
            "[14:30:00] hydroXis",
        )
        assert panel.killed_by_combo.current() == 0
        assert "HYDROXIS killed Woo Wildrock" in panel.text.content
        assert panel.text.seen is True

    def test_render_selected_event_switches_textbox_content(self) -> None:
        panel = self._make_panel()
        panel.add_death_event({
            "timestamp": datetime(2026, 1, 9, 14, 30, 0),
            "killer": "A",
            "lines": ["[CHAT WINDOW TEXT] [t] A killed Woo Wildrock"],
            "target": "Woo Wildrock",
        })
        panel.add_death_event({
            "timestamp": datetime(2026, 1, 9, 14, 31, 0),
            "killer": "B",
            "lines": ["[CHAT WINDOW TEXT] [t] B killed Woo Wildrock"],
            "target": "Woo Wildrock",
        })

        panel.killed_by_combo.current(1)
        panel.render_selected_event()

        assert "A killed Woo Wildrock" in panel.text.content
        assert "B killed Woo Wildrock" not in panel.text.content

    def test_clear_resets_dropdown_and_placeholder(self) -> None:
        panel = self._make_panel()
        panel.add_death_event({
            "timestamp": datetime(2026, 1, 9, 14, 30, 0),
            "killer": "HYDROXIS",
            "lines": ["[CHAT WINDOW TEXT] [t] HYDROXIS killed Woo Wildrock"],
            "target": "Woo Wildrock",
        })

        panel.clear()

        assert panel.text.content == DeathSnippetPanel.EMPTY_TEXT_PLACEHOLDER
        assert panel.killed_by_combo.values == ()
        assert panel.killed_by_combo.state == "disabled"
        assert panel.killed_by_combo.get() == DeathSnippetPanel.EMPTY_DROPDOWN_PLACEHOLDER

    def test_collect_color_spans_colors_adjacent_pairs(self) -> None:
        line = "BIOLLANTE damages Woo Whirlwind: 99 (27 Positive Energy 50 Fire 22 Negative Energy)"
        spans = DeathSnippetPanel._collect_color_spans(line)

        colored_tokens = [line[start:end] for start, end, _ in spans]
        assert "27" in colored_tokens
        assert "Positive Energy" in colored_tokens
        assert "50" in colored_tokens
        assert "Fire" in colored_tokens
        assert "22" in colored_tokens
        assert "Negative Energy" in colored_tokens

    def test_collect_color_spans_does_not_color_non_adjacent_immunity_number(self) -> None:
        line = "Damage Immunity absorbs 10 point(s) of Fire"
        spans = DeathSnippetPanel._collect_color_spans(line)

        colored_tokens = [line[start:end] for start, end, _ in spans]
        assert "Fire" in colored_tokens
        assert "10" not in colored_tokens

    def test_collect_color_spans_colors_save_vs_damage_type(self) -> None:
        line = "Woo Whirlwind : Fortitude Save vs. Acid : *success* : (20 + 50 = 70 vs. DC: 52)"
        spans = DeathSnippetPanel._collect_color_spans(line)
        colored_tokens = [line[start:end] for start, end, _ in spans]
        assert "Acid" in colored_tokens

    def test_collect_color_spans_skips_spell_resist_spell_names(self) -> None:
        line = "SPELL RESIST: Woo Whirlwind attempts to resist: Acid Fog - Result: FAILED"
        spans = DeathSnippetPanel._collect_color_spans(line)
        colored_tokens = [line[start:end] for start, end, _ in spans]
        assert "Acid" not in colored_tokens

    def test_collect_color_spans_skips_wall_of_fire_spell_name(self) -> None:
        line = "SPELL RESIST: Woo Whirlwind attempts to resist: Wall of Fire - Result: FAILED"
        spans = DeathSnippetPanel._collect_color_spans(line)
        colored_tokens = [line[start:end] for start, end, _ in spans]
        assert "Fire" not in colored_tokens

    def test_render_selected_event_uses_tags_for_colored_tokens(self) -> None:
        panel = self._make_panel()
        panel.add_death_event({
            "timestamp": datetime(2026, 1, 9, 14, 30, 0),
            "killer": "HYDROXIS",
            "lines": ["[CHAT WINDOW TEXT] [t] test damages target: 27 (27 Fire)"],
            "target": "Woo Wildrock",
        })

        tagged_text = [text for _idx, text, tag in panel.text.inserts if tag is not None]
        assert "27" in tagged_text
        assert "Fire" in tagged_text

    def test_render_selected_event_skips_unchanged_selection(self) -> None:
        panel = self._make_panel()
        panel.add_death_event({
            "timestamp": datetime(2026, 1, 9, 14, 30, 0),
            "killer": "HYDROXIS",
            "lines": ["[CHAT WINDOW TEXT] [t] test damages target: 27 Fire"],
            "target": "Woo Wildrock",
        })
        first_insert_count = len(panel.text.inserts)

        panel.render_selected_event()

        assert len(panel.text.inserts) == first_insert_count

    def test_insert_colored_line_fast_path_for_non_damage_lines(self) -> None:
        panel = self._make_panel()
        panel.text.delete("1.0", "end")
        panel._insert_colored_line("[t] HYDROXIS killed Woo Wildrock")

        assert not panel.text.tag_configs
        assert panel.text.content == "[t] HYDROXIS killed Woo Wildrock\n"

    def test_extract_opponent_names_from_hostile_lines_targeting_killed(self) -> None:
        lines = [
            "[Wed Jan 09 14:30:00] Ash-Tusk Clan Sniper attacks Woo Whirlwind : *hit* : (12 + 56 = 68)",
            "[Wed Jan 09 14:30:01] GENERAL KORGAN damages Woo Whirlwind: 40 (0 Physical 4 Divine 36 Electrical 0 Fire)",
            "[Wed Jan 09 14:30:02] HYDROXIS killed Woo Whirlwind",
            "[Wed Jan 09 14:30:03] GENERAL KORGAN casts unknown spell",
        ]

        opponents = DeathSnippetPanel._extract_opponent_names(
            lines=lines,
            killed_name="Woo Whirlwind",
            killer_name="HYDROXIS",
        )

        assert "HYDROXIS" in opponents
        assert "Ash-Tusk Clan Sniper" in opponents
        assert "GENERAL KORGAN" in opponents

    def test_render_colors_killed_name_in_save_and_spell_resist_lines(self) -> None:
        panel = self._make_panel()
        panel.add_death_event({
            "timestamp": datetime(2026, 1, 9, 14, 30, 0),
            "killer": "HYDROXIS",
            "target": "Woo Whirlwind",
            "lines": [
                "[CHAT WINDOW TEXT] [t] Woo Whirlwind : Fortitude Save vs. Poison : *success* : (8 + 50 = 58 vs. DC: 55)",
                "[CHAT WINDOW TEXT] [t] SPELL RESIST: Woo Whirlwind attempts to resist: Acid Fog - Result: FAILED",
            ],
        })

        killed_tag = next(
            tag for tag, conf in panel.text.tag_configs.items()
            if conf.get("foreground") == DeathSnippetPanel.KILLED_NAME_COLOR
        )
        killed_tagged_text = [text for _idx, text, tag in panel.text.inserts if tag == killed_tag]

        assert "Woo Whirlwind" in killed_tagged_text
        assert killed_tagged_text.count("Woo Whirlwind") == 2

    def test_render_colors_opponents_from_attacks_and_damages_against_killed(self) -> None:
        panel = self._make_panel()
        panel.add_death_event({
            "timestamp": datetime(2026, 1, 9, 14, 30, 0),
            "killer": "HYDROXIS",
            "target": "Woo Whirlwind",
            "lines": [
                "[CHAT WINDOW TEXT] [t] Ash-Tusk Clan Sniper attacks Woo Whirlwind : *hit* : (12 + 56 = 68)",
                "[CHAT WINDOW TEXT] [t] GENERAL KORGAN damages Woo Whirlwind: 40 (0 Physical 4 Divine 36 Electrical 0 Fire)",
                "[CHAT WINDOW TEXT] [t] HYDROXIS killed Woo Whirlwind",
            ],
        })

        opponent_tag = next(
            tag for tag, conf in panel.text.tag_configs.items()
            if conf.get("foreground") == DeathSnippetPanel.OPPONENT_NAME_COLOR
        )
        opponent_tagged_text = [text for _idx, text, tag in panel.text.inserts if tag == opponent_tag]

        assert "Ash-Tusk Clan Sniper" in opponent_tagged_text
        assert "GENERAL KORGAN" in opponent_tagged_text
        assert "HYDROXIS" in opponent_tagged_text

    def test_clear_character_name_restores_hint_and_empty_value(self) -> None:
        panel = self._make_panel()
        panel.set_character_name("Woo Wildrock")

        panel.clear_character_name()

        assert panel.get_character_name() == ""
        assert panel.character_name_var.get() == DeathSnippetPanel.CHARACTER_NAME_HINT
        assert panel._character_hint_active is True
        assert panel._character_entry_foreground == "gray"

    def test_clear_character_name_notifies_callback_with_empty_name(self) -> None:
        panel = self._make_panel()
        callback = []
        panel._on_character_name_changed = callback.append
        panel.set_character_name("Woo Wildrock")
        callback.clear()

        panel.clear_character_name()

        assert callback == [""]

    def test_apply_line_wrap_setting_defaults_to_wrapped_without_horizontal_scroll(self) -> None:
        panel = self._make_panel()

        panel._apply_line_wrap_setting()

        assert panel.text.config["wrap"] == "word"
        assert panel.text.config["xscrollcommand"] == ""
        assert panel.hscroll.winfo_ismapped() is False

    def test_line_wrap_toggle_off_disables_wrap_and_shows_horizontal_scrollbar(self) -> None:
        panel = self._make_panel()
        panel.line_wrap_var.set(False)

        panel._on_line_wrap_toggled()

        assert panel.text.config["wrap"] == "none"
        assert panel.text.config["xscrollcommand"] == panel.hscroll.set
        assert panel.hscroll.command == panel.text.xview
        assert panel.hscroll.winfo_ismapped() is True

    def test_line_wrap_toggle_on_hides_horizontal_scrollbar(self) -> None:
        panel = self._make_panel()
        panel.line_wrap_var.set(False)
        panel._on_line_wrap_toggled()
        assert panel.hscroll.winfo_ismapped() is True

        panel.line_wrap_var.set(True)
        panel._on_line_wrap_toggled()

        assert panel.text.config["wrap"] == "word"
        assert panel.text.config["xscrollcommand"] == ""
        assert panel.hscroll.winfo_ismapped() is False

    def test_prepare_display_lines_for_wrap_mode_no_wrap_pads_shorter_lines(self) -> None:
        panel = self._make_panel()
        panel.line_wrap_var.set(False)
        panel.theme_font = self._make_fake_font()
        lines = ["abcd", "ab"]

        prepared = panel._prepare_display_lines_for_wrap_mode(lines)

        assert prepared[0] == "abcd"
        assert prepared[1] == "ab  "

    def test_prepare_display_lines_for_wrap_mode_wrap_on_keeps_lines_unchanged(self) -> None:
        panel = self._make_panel()
        panel.line_wrap_var.set(True)
        panel.theme_font = self._make_fake_font()
        lines = ["abcd", "ab"]

        prepared = panel._prepare_display_lines_for_wrap_mode(lines)

        assert prepared == lines

    def test_on_line_wrap_toggled_forces_rerender(self) -> None:
        panel = self._make_panel()
        panel.render_selected_event = lambda: panel.text.insert("end", "rerendered")
        panel._last_render_key = (0, 1)

        panel._on_line_wrap_toggled()

        assert panel._last_render_key is None
        assert "rerendered" in panel.text.content

    def test_on_line_wrap_toggled_preserves_vertical_scroll_position(self) -> None:
        panel = self._make_panel()
        panel.text.yview_start = 0.42
        panel.text.index = lambda _expr: (_ for _ in ()).throw(AttributeError("no index"))

        def _simulate_render_jump_to_bottom() -> None:
            panel.text.yview_start = 1.0

        panel.render_selected_event = _simulate_render_jump_to_bottom
        panel._on_line_wrap_toggled()

        assert panel.text.yview_start == 0.42

    def test_on_line_wrap_toggled_restores_top_visible_index_first(self) -> None:
        panel = self._make_panel()
        panel.text.top_index = "17.0"
        panel.text.yview_start = 0.31

        def _simulate_render_jump_to_bottom() -> None:
            panel.text.top_index = "200.0"
            panel.text.yview_start = 1.0

        panel.render_selected_event = _simulate_render_jump_to_bottom
        panel._on_line_wrap_toggled()

        assert panel.text.top_index == "17.0"
