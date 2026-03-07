"""Unit tests for DeathSnippetPanel behavior."""

from datetime import datetime

from app.ui.widgets.death_snippet_panel import DeathSnippetPanel


class _FakeText:
    def __init__(self, content: str = "") -> None:
        self.content = content
        self.seen = False
        self.tag_configs = {}
        self.inserts = []

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
        return panel

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
            "14:55:23 HYDROXIS",
            "14:30:00 hydroXis",
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
        line = "27 Positive Energy 50 Fire 22 Negative Energy"
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

    def test_render_selected_event_uses_tags_for_colored_tokens(self) -> None:
        panel = self._make_panel()
        panel.add_death_event({
            "timestamp": datetime(2026, 1, 9, 14, 30, 0),
            "killer": "HYDROXIS",
            "lines": ["[CHAT WINDOW TEXT] [t] test damages target: 27 Fire"],
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
