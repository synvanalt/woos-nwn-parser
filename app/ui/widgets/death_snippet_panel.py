"""Death snippet panel widget for Woo's NWN Parser UI."""

import re
from datetime import datetime
import tkinter as tk
from tkinter import ttk, font
from typing import Any, Dict, Optional

from ...constants import DAMAGE_TYPE_PALETTE
from ..formatters import damage_type_to_color


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


class DeathSnippetPanel(ttk.Frame):
    """Panel for displaying death-related log snippets."""

    EMPTY_DROPDOWN_PLACEHOLDER = "Hurray! You have not died (yet)"
    EMPTY_TEXT_PLACEHOLDER = "Last 100 character-related log lines before death will appear here"
    _DAMAGE_KEYWORDS, _PAIR_PATTERNS, _TYPE_PATTERNS = _compile_damage_patterns()

    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(parent, padding="10")
        self.death_events: list[Dict[str, Any]] = []
        self._event_sequence: int = 0
        self.killed_by_var = tk.StringVar(value=self.EMPTY_DROPDOWN_PLACEHOLDER)
        self._text_tags_by_color: Dict[str, str] = {}
        self._last_render_key: Optional[tuple] = None

        try:
            self.theme_font = font.nametofont("SunValleyBodyFont")
        except tk.TclError:
            self.theme_font = font.Font(family="Courier", size=10)

        self.setup_ui()
        self._set_combo_values()
        self._show_placeholder()

    def setup_ui(self) -> None:
        selector_frame = ttk.Frame(self)
        selector_frame.pack(fill="x", padx=(10, 10), pady=(8, 10))

        def _on_death_selected(_event: tk.Event) -> None:
            _event.widget.selection_clear()
            self.render_selected_event()

        ttk.Label(selector_frame, text="Killed by:").pack(side="left", padx=(0, 5))
        self.killed_by_combo = ttk.Combobox(
            selector_frame,
            state="disabled",
            width=40,
            textvariable=self.killed_by_var,
        )
        self.killed_by_combo.pack(side="left", fill="x", expand=True)
        self.killed_by_combo.bind("<<ComboboxSelected>>", _on_death_selected)

        scroll = ttk.Scrollbar(self)
        scroll.pack(side="right", fill="y")

        self.text = tk.Text(
            self,
            font=self.theme_font,
            wrap="word",
            yscrollcommand=scroll.set,
            height=30,
        )
        self.text.pack(fill="both", expand=True)
        scroll.config(command=self.text.yview)

    @staticmethod
    def _sanitize_display_line(line: str) -> str:
        """Remove NWN chat boilerplate prefix for cleaner display."""
        return re.sub(r"^\[CHAT WINDOW TEXT]\s*", "", line)

    def _show_placeholder(self) -> None:
        """Show default text when there are no death snippets."""
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", self.EMPTY_TEXT_PLACEHOLDER)
        self._last_render_key = None

    @staticmethod
    def _event_sort_timestamp(event: Dict[str, Any]) -> datetime:
        """Return event timestamp for sorting, with safe fallback."""
        timestamp = event.get("timestamp")
        if isinstance(timestamp, datetime):
            return timestamp
        return datetime.min

    @staticmethod
    def _format_dropdown_value(event: Dict[str, Any]) -> str:
        """Build dropdown value text as HH:MM:SS plus original killer name."""
        timestamp = event.get("timestamp")
        killer = str(event.get("killer", "")).strip()

        if isinstance(timestamp, datetime):
            timestamp_text = timestamp.strftime("%H:%M:%S")
        else:
            timestamp_text = "--:--:--"

        if not killer:
            killer = "Unknown"

        return f"{timestamp_text} {killer}"

    def _set_combo_values(self) -> None:
        """Refresh combobox values from current death events."""
        values = [self._format_dropdown_value(event) for event in self.death_events]
        self.killed_by_combo["values"] = values
        if values:
            self.killed_by_combo.configure(state="readonly")
        else:
            # Set display text before disabling to ensure it remains visible.
            self.killed_by_combo.configure(state="normal")
            self.killed_by_var.set(self.EMPTY_DROPDOWN_PLACEHOLDER)
            self.killed_by_combo.configure(state="disabled")

    def _get_selected_event(self) -> Optional[Dict[str, Any]]:
        """Return selected death event or None if no valid selection exists."""
        if not self.death_events:
            return None

        selected_index = self.killed_by_combo.current()
        if 0 <= selected_index < len(self.death_events):
            return self.death_events[selected_index]

        selected_value = self.killed_by_combo.get()
        values = list(self.killed_by_combo.cget("values"))
        if selected_value and selected_value in values:
            fallback_index = values.index(selected_value)
            if 0 <= fallback_index < len(self.death_events):
                return self.death_events[fallback_index]

        return None

    @classmethod
    def _line_may_have_damage_type(cls, line: str) -> bool:
        lowered = line.lower()
        return any(keyword in lowered for keyword in cls._DAMAGE_KEYWORDS)

    @staticmethod
    def _spans_overlap(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
        for span_start, span_end in spans:
            if start < span_end and end > span_start:
                return True
        return False

    @classmethod
    def _collect_color_spans(cls, line: str) -> list[tuple[int, int, str]]:
        """Collect color spans for one line.

        Returns tuples of (start_idx, end_idx, color_key).
        """
        if not line or not cls._line_may_have_damage_type(line):
            return []

        spans: list[tuple[int, int, str]] = []
        pair_occupied: list[tuple[int, int]] = []

        # First pass: adjacent "<number> <damage type>" pairs color both tokens.
        for color_key, pattern in cls._PAIR_PATTERNS:
            for match in pattern.finditer(line):
                num_start, num_end = match.span("num")
                type_start, type_end = match.span("dtype")
                spans.append((num_start, num_end, color_key))
                spans.append((type_start, type_end, color_key))
                pair_occupied.append((num_start, num_end))
                pair_occupied.append((type_start, type_end))

        # Second pass: standalone damage-type words (only if not already in pair spans).
        for color_key, pattern in cls._TYPE_PATTERNS:
            for match in pattern.finditer(line):
                start, end = match.span(0)
                if cls._spans_overlap(start, end, pair_occupied):
                    continue
                spans.append((start, end, color_key))

        return sorted(spans, key=lambda item: (item[0], item[1]))

    def _get_or_create_text_tag(self, color_key: str) -> str:
        """Get cached text tag for color key, configuring it once."""
        color = damage_type_to_color(color_key)
        tag_name = self._text_tags_by_color.get(color)
        if tag_name is not None:
            return tag_name
        tag_name = f"dt_{color_key.replace(' ', '_')}_{len(self._text_tags_by_color)}"
        self.text.tag_configure(tag_name, foreground=color)
        self._text_tags_by_color[color] = tag_name
        return tag_name

    def _insert_colored_line(self, line: str) -> None:
        """Insert one line with damage-type-aware coloring."""
        spans = self._collect_color_spans(line)
        if not spans:
            self.text.insert(tk.END, f"{line}\n")
            return

        cursor = 0
        for start, end, color_key in spans:
            if start < cursor:
                continue
            if start > cursor:
                self.text.insert(tk.END, line[cursor:start])
            tag_name = self._get_or_create_text_tag(color_key)
            self.text.insert(tk.END, line[start:end], tag_name)
            cursor = end

        if cursor < len(line):
            self.text.insert(tk.END, line[cursor:])
        self.text.insert(tk.END, "\n")

    def render_selected_event(self) -> None:
        """Render snippet lines for the currently selected death event."""
        selected_event = self._get_selected_event()
        if selected_event is None:
            self._show_placeholder()
            return

        selected_index = self.killed_by_combo.current()
        selected_seq = selected_event.get("_seq")
        render_key = (selected_index, selected_seq)
        if render_key == self._last_render_key:
            return

        lines = selected_event.get("lines", [])
        self.text.delete("1.0", tk.END)
        for line in lines:
            self._insert_colored_line(self._sanitize_display_line(str(line)))
        self.text.see(tk.END)
        self._last_render_key = render_key

    def add_death_event(self, event: Dict[str, Any]) -> None:
        """Add a death snippet event and select newest entry."""
        lines = event.get("lines", [])
        if not lines:
            return

        event_copy = dict(event)
        event_copy["_seq"] = self._event_sequence
        self._event_sequence += 1
        self.death_events.append(event_copy)
        self.death_events.sort(
            key=lambda item: (self._event_sort_timestamp(item), int(item.get("_seq", 0))),
            reverse=True,
        )

        self._set_combo_values()
        self._last_render_key = None
        if self.death_events:
            self.killed_by_combo.current(0)
            self.render_selected_event()

    def clear(self) -> None:
        """Clear all recorded death snippets."""
        self.death_events.clear()
        self._event_sequence = 0
        self._last_render_key = None
        self._set_combo_values()
        self._show_placeholder()
