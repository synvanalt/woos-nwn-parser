"""Death snippet panel widget for Woo's NWN Parser UI."""

import re
from datetime import datetime
import tkinter as tk
from tkinter import ttk, font
from typing import Any, Callable, Dict, Optional

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
    CHARACTER_NAME_HINT = 'Whisper "wooparseme" in-game to auto-identify your character'
    DEFAULT_FALLBACK_DEATH_LINE = "Your God refuses to hear your prayers!"
    CONFIG_LABEL_WIDTH = 14
    KILLED_NAME_COLOR = "#98FEFF"
    OPPONENT_NAME_COLOR = "#CD98CC"
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

    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(parent, padding="10")
        self._notebook = parent
        self.death_events: list[Dict[str, Any]] = []
        self._event_sequence: int = 0
        self.killed_by_var = tk.StringVar(value=self.EMPTY_DROPDOWN_PLACEHOLDER)
        self.character_name_var = tk.StringVar(value="")
        self.fallback_death_line_var = tk.StringVar(value=self.DEFAULT_FALLBACK_DEATH_LINE)
        self.line_wrap_var = tk.BooleanVar(value=True)
        self._text_tags_by_color: Dict[str, str] = {}
        self._last_render_key: Optional[tuple] = None
        self._name_pattern_cache: Dict[str, re.Pattern[str]] = {}
        self._character_hint_active = False
        self._suppress_identity_callbacks = False
        self._on_character_name_changed: Optional[Callable[[str], None]] = None
        self._on_fallback_line_changed: Optional[Callable[[str], None]] = None

        try:
            self.theme_font = font.nametofont("SunValleyBodyFont")
        except tk.TclError:
            self.theme_font = font.Font(family="Courier", size=10)

        self.setup_ui()
        self._notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed, add=True)
        self._set_combo_values()
        self._show_placeholder()

    def setup_ui(self) -> None:
        config_frame = ttk.Frame(self)
        config_frame.pack(fill="x", padx=(10, 10), pady=(0, 0))

        character_row = ttk.Frame(config_frame)
        character_row.pack(fill="x", pady=(0, 7))
        ttk.Label(
            character_row,
            text="Character Name:",
            width=self.CONFIG_LABEL_WIDTH,
            anchor="w",
        ).pack(side="left", padx=(0, 5))
        self.character_name_entry = ttk.Entry(
            character_row,
            textvariable=self.character_name_var,
        )
        self.character_name_entry.pack(side="left", fill="x", expand=True)
        self.character_name_entry.bind("<FocusIn>", self._on_character_name_focus_in)
        self.character_name_entry.bind("<FocusOut>", self._on_character_name_focus_out)

        fallback_row = ttk.Frame(config_frame)
        fallback_row.pack(fill="x", pady=(0, 7))
        ttk.Label(
            fallback_row,
            text="Fallback Log Line:",
            width=self.CONFIG_LABEL_WIDTH,
            anchor="w",
        ).pack(side="left", padx=(0, 5))
        self.fallback_death_line_entry = ttk.Entry(
            fallback_row,
            textvariable=self.fallback_death_line_var,
        )
        self.fallback_death_line_entry.pack(side="left", fill="x", expand=True)
        self._set_fallback_entry_foreground("gray")

        selector_frame = ttk.Frame(self)
        selector_frame.pack(fill="x", padx=(10, 10), pady=(0, 10))

        def _on_death_selected(_event: tk.Event) -> None:
            _event.widget.selection_clear()
            self.render_selected_event()

        ttk.Label(
            selector_frame,
            text="Killed by:",
            width=self.CONFIG_LABEL_WIDTH,
            anchor="w",
        ).pack(side="left", padx=(0, 5))
        self.killed_by_combo = ttk.Combobox(
            selector_frame,
            state="disabled",
            width=40,
            textvariable=self.killed_by_var,
        )
        self.killed_by_combo.pack(side="left", fill="x", expand=True)
        self.killed_by_combo.bind("<<ComboboxSelected>>", _on_death_selected)

        ttk.Checkbutton(
            selector_frame,
            text="Line Wrap",
            variable=self.line_wrap_var,
            command=self._on_line_wrap_toggled,
        ).pack(side="left", padx=(8, 0))

        text_frame = ttk.Frame(self)
        text_frame.pack(fill="both", expand=True)
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)

        vscroll = ttk.Scrollbar(text_frame, orient="vertical")
        self.hscroll = ttk.Scrollbar(text_frame, orient="horizontal")
        self.text = tk.Text(
            text_frame,
            font=self.theme_font,
            wrap="word",
            yscrollcommand=vscroll.set,
            height=30,
        )
        self.text.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        vscroll.config(command=self.text.yview)
        self._apply_line_wrap_setting()
        self._enable_character_name_hint_if_empty()
        self.character_name_var.trace_add("write", self._on_character_name_text_changed)
        self.fallback_death_line_var.trace_add("write", self._on_fallback_line_text_changed)

    def _on_notebook_tab_changed(self, _event: tk.Event) -> None:
        """Set default focus to selector dropdown when entering this panel."""
        if not hasattr(self, "_notebook"):
            return
        try:
            selected_tab = self._notebook.nametowidget(self._notebook.select())
        except tk.TclError:
            return
        if selected_tab is not self:
            return
        try:
            self.killed_by_combo.focus_set()
        except tk.TclError:
            pass

    @staticmethod
    def _normalize_name(value: str) -> str:
        """Normalize user-entered character names."""
        return " ".join(value.strip().split())

    def configure_identity_callbacks(
        self,
        *,
        on_character_name_changed: Optional[Callable[[str], None]] = None,
        on_fallback_line_changed: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Configure callbacks for identity/fallback entry changes."""
        self._on_character_name_changed = on_character_name_changed
        self._on_fallback_line_changed = on_fallback_line_changed

    def _set_character_entry_foreground(self, color: str) -> None:
        """Set the character name entry foreground with ttk/tk compatibility."""
        if not hasattr(self, "character_name_entry"):
            return
        try:
            self.character_name_entry.configure(foreground=color)
        except tk.TclError:
            pass

    def _set_fallback_entry_foreground(self, color: str) -> None:
        """Set the fallback line entry foreground with ttk/tk compatibility."""
        if not hasattr(self, "fallback_death_line_entry"):
            return
        try:
            self.fallback_death_line_entry.configure(foreground=color)
        except tk.TclError:
            pass

    def _set_combo_text_foreground(self, color: str) -> None:
        """Set dropdown text color with ttk/tk compatibility."""
        if not hasattr(self, "killed_by_combo"):
            return
        try:
            self.killed_by_combo.configure(foreground=color)
        except tk.TclError:
            pass

    def _enable_character_name_hint_if_empty(self) -> None:
        """Show hint text in character name entry when value is empty."""
        if self._normalize_name(self.character_name_var.get()):
            return
        self._suppress_identity_callbacks = True
        self._character_hint_active = True
        self.character_name_var.set(self.CHARACTER_NAME_HINT)
        self._set_character_entry_foreground("gray")
        self._suppress_identity_callbacks = False

    def _on_character_name_focus_in(self, _event: tk.Event) -> None:
        """Clear hint text on focus-in for direct editing."""
        if not self._character_hint_active:
            return
        self._suppress_identity_callbacks = True
        self.character_name_var.set("")
        self._character_hint_active = False
        self._set_character_entry_foreground("")
        self._suppress_identity_callbacks = False

    def _on_character_name_focus_out(self, _event: tk.Event) -> None:
        """Restore hint text if user leaves the field empty."""
        if self._normalize_name(self.character_name_var.get()):
            return
        self._enable_character_name_hint_if_empty()
        self._notify_character_name_changed()

    def _on_character_name_text_changed(self, *_args) -> None:
        """Handle character name text edits."""
        if self._suppress_identity_callbacks:
            return
        if self._character_hint_active and self.character_name_var.get() != self.CHARACTER_NAME_HINT:
            self._character_hint_active = False
            self._set_character_entry_foreground("")
        self._notify_character_name_changed()

    def _on_fallback_line_text_changed(self, *_args) -> None:
        """Handle fallback death-line text edits."""
        if self._suppress_identity_callbacks:
            return
        if self._on_fallback_line_changed is not None:
            self._on_fallback_line_changed(self.get_fallback_death_line())

    def _notify_character_name_changed(self) -> None:
        """Notify controller callback with normalized character name."""
        if self._on_character_name_changed is None:
            return
        self._on_character_name_changed(self.get_character_name())

    def get_character_name(self) -> str:
        """Return normalized character name, excluding hint text."""
        if self._character_hint_active:
            return ""
        return self._normalize_name(self.character_name_var.get())

    def set_character_name(self, name: str) -> None:
        """Set character name field value and notify callback."""
        normalized = self._normalize_name(name)
        self._suppress_identity_callbacks = True
        if normalized:
            self._character_hint_active = False
            self.character_name_var.set(normalized)
            self._set_character_entry_foreground("")
        else:
            self.character_name_var.set("")
            self._enable_character_name_hint_if_empty()
        self._suppress_identity_callbacks = False
        self._notify_character_name_changed()

    def get_fallback_death_line(self) -> str:
        """Return fallback death-line text."""
        return self.fallback_death_line_var.get().strip()

    def set_fallback_death_line(self, line: str) -> None:
        """Set fallback death-line field value and notify callback."""
        self._suppress_identity_callbacks = True
        self.fallback_death_line_var.set(line.strip())
        self._suppress_identity_callbacks = False
        if self._on_fallback_line_changed is not None:
            self._on_fallback_line_changed(self.get_fallback_death_line())

    def _on_line_wrap_toggled(self) -> None:
        """Apply line-wrap behavior from the toggle state."""
        top_visible_index: Optional[str] = None
        yview_start: Optional[float] = None
        try:
            top_visible_index = str(self.text.index("@0,0"))
        except (AttributeError, tk.TclError):
            top_visible_index = None
        try:
            yview = self.text.yview()
            if isinstance(yview, tuple) and yview:
                yview_start = float(yview[0])
        except (AttributeError, tk.TclError, ValueError, TypeError):
            yview_start = None

        self._apply_line_wrap_setting()
        self._last_render_key = None
        self.render_selected_event()
        if top_visible_index:
            try:
                self.text.yview(top_visible_index)
                return
            except (AttributeError, tk.TclError):
                pass
        if yview_start is not None:
            try:
                self.text.yview_moveto(yview_start)
            except (AttributeError, tk.TclError):
                pass

    def _apply_line_wrap_setting(self) -> None:
        """Configure text wrapping and horizontal scrollbar visibility."""
        if bool(self.line_wrap_var.get()):
            self.text.configure(wrap="word", xscrollcommand="")
            if self.hscroll.winfo_manager() == "grid":
                self.hscroll.grid_remove()
            return

        self.text.configure(wrap="none", xscrollcommand=self.hscroll.set)
        self.hscroll.config(command=self.text.xview)
        self.hscroll.grid(row=1, column=0, sticky="ew")

    def _prepare_display_lines_for_wrap_mode(self, lines: list[str]) -> list[str]:
        """Return lines adjusted for current wrap mode.

        In no-wrap mode, pad each line to the widest line width to stabilize
        horizontal scrollbar proportions while vertically scrolling.
        """
        if bool(self.line_wrap_var.get()) or not lines:
            return lines
        if not hasattr(self, "theme_font"):
            return lines

        line_widths = [self.theme_font.measure(line) for line in lines]
        max_width = max(line_widths, default=0)
        if max_width <= 0:
            return lines

        space_width = max(1, int(self.theme_font.measure(" ")))
        padded_lines: list[str] = []
        for line, width in zip(lines, line_widths):
            deficit = max_width - width
            if deficit <= 0:
                padded_lines.append(line)
                continue
            padding_spaces = (deficit + space_width - 1) // space_width
            padded_lines.append(f"{line}{' ' * padding_spaces}")

        return padded_lines

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

        return f"[{timestamp_text}] {killer}"

    def _set_combo_values(self) -> None:
        """Refresh combobox values from current death events."""
        values = [self._format_dropdown_value(event) for event in self.death_events]
        self.killed_by_combo["values"] = values
        if values:
            self._set_combo_text_foreground("")
            self.killed_by_combo.configure(state="readonly")
        else:
            # Set display text before disabling to ensure it remains visible.
            self._set_combo_text_foreground("gray")
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
        """Collect damage color spans for one line using context-gated matching.

        Returns tuples of (start_idx, end_idx, color_key).
        """
        if not line:
            return []

        spans: list[tuple[int, int, str]] = []
        line_has_keyword = cls._line_may_have_damage_type(line)

        # Context 1: "Damage Immunity absorbs ... of <Type>" -> color only <Type>.
        if cls._DAMAGE_IMMUNITY_PREFIX in line and line_has_keyword:
            immunity_match = cls._IMMUNITY_OF_PATTERN.search(line)
            if immunity_match:
                dtype_text = immunity_match.group("dtype")
                dtype_start = immunity_match.start("dtype")
                for color_key, pattern in cls._TYPE_PATTERNS:
                    type_match = pattern.fullmatch(dtype_text.strip())
                    if not type_match:
                        continue
                    # Map match inside stripped segment back to absolute indices.
                    stripped = dtype_text.strip()
                    local_offset = dtype_text.find(stripped)
                    abs_start = dtype_start + local_offset
                    abs_end = abs_start + len(stripped)
                    spans.append((abs_start, abs_end, color_key))
                    break

        # Context 2: "X damages Y: N (breakdown)" -> color adjacent number/type pairs in breakdown only.
        if " damages " in line and "(" in line and ")" in line:
            breakdown_match = cls._DAMAGE_BREAKDOWN_PATTERN.search(line)
            if breakdown_match:
                breakdown = breakdown_match.group("breakdown")
                breakdown_start = breakdown_match.start("breakdown")
                for color_key, pattern in cls._PAIR_PATTERNS:
                    for pair_match in pattern.finditer(breakdown):
                        num_start, num_end = pair_match.span("num")
                        type_start, type_end = pair_match.span("dtype")
                        spans.append((breakdown_start + num_start, breakdown_start + num_end, color_key))
                        spans.append((breakdown_start + type_start, breakdown_start + type_end, color_key))

        # Context 3: "... Save vs. <Type> : ..." -> color only <Type>.
        if cls._SAVE_VS_MARKER in line and line_has_keyword:
            save_match = cls._SAVE_VS_PATTERN.search(line)
            if save_match:
                dtype_text = save_match.group("dtype").strip()
                dtype_start = save_match.start("dtype")
                for color_key, pattern in cls._TYPE_PATTERNS:
                    type_match = pattern.fullmatch(dtype_text)
                    if not type_match:
                        continue
                    spans.append((dtype_start, dtype_start + len(dtype_text), color_key))
                    break

        # Deduplicate and keep stable order.
        spans = sorted(set(spans), key=lambda item: (item[0], item[1]))
        return sorted(spans, key=lambda item: (item[0], item[1]))

    def _get_or_create_text_tag(self, color_key: str) -> str:
        """Get cached text tag for color key, configuring it once."""
        color = damage_type_to_color(color_key)
        return self._get_or_create_color_tag(color, f"dt_{color_key.replace(' ', '_')}")

    def _get_or_create_color_tag(self, color: str, name_prefix: str) -> str:
        """Get cached text tag for a direct color value."""
        tag_name = self._text_tags_by_color.get(color)
        if tag_name is not None:
            return tag_name
        tag_name = f"{name_prefix}_{len(self._text_tags_by_color)}"
        self.text.tag_configure(tag_name, foreground=color)
        self._text_tags_by_color[color] = tag_name
        return tag_name

    @classmethod
    def _strip_timestamp_prefix(cls, line: str) -> str:
        """Remove leading timestamp prefix from a display line."""
        return cls._TIMESTAMP_PREFIX.sub("", line, count=1)

    def _get_name_pattern(self, name: str) -> re.Pattern[str]:
        """Get cached exact token-boundary regex for a name."""
        cached = self._name_pattern_cache.get(name)
        if cached is not None:
            return cached
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")
        self._name_pattern_cache[name] = pattern
        return pattern

    @staticmethod
    def _line_contains_any_name(line: str, names: set[str]) -> bool:
        """Fast substring gate before regex matching names."""
        if not names:
            return False
        lowered = line.lower()
        return any(name.lower() in lowered for name in names if name)

    def _collect_name_spans(
        self,
        line: str,
        killed_name: str,
        opponent_names: set[str],
    ) -> list[tuple[int, int, str]]:
        """Collect name color spans with killed/opponent precedence."""
        spans: list[tuple[int, int, str]] = []

        if killed_name:
            killed_pattern = self._get_name_pattern(killed_name)
            for match in killed_pattern.finditer(line):
                spans.append((match.start(), match.end(), "killed"))

        occupied = [(start, end) for start, end, _kind in spans]
        if not self._line_contains_any_name(line, opponent_names):
            return spans

        for opponent in sorted(opponent_names, key=len, reverse=True):
            if not opponent:
                continue
            pattern = self._get_name_pattern(opponent)
            for match in pattern.finditer(line):
                start, end = match.span(0)
                if self._spans_overlap(start, end, occupied):
                    continue
                spans.append((start, end, "opponent"))
                occupied.append((start, end))

        return sorted(spans, key=lambda item: (item[0], item[1]))

    @classmethod
    def _extract_opponent_names(
        cls,
        lines: list[str],
        killed_name: str,
        killer_name: str,
    ) -> set[str]:
        """Extract opponents from lines that explicitly target the killed character."""
        opponents: set[str] = set()
        killed_fold = killed_name.casefold()

        killer = cls._normalize_name(killer_name)
        if killer and killer.casefold() != killed_fold:
            opponents.add(killer)

        for line in lines:
            scan_line = cls._strip_timestamp_prefix(line)
            for pattern, actor_group in (
                (cls._ATTACKS_TARGET, "attacker"),
                (cls._DAMAGES_TARGET, "attacker"),
                (cls._KILLED_TARGET, "killer"),
            ):
                match = pattern.search(scan_line)
                if not match:
                    continue
                target = cls._normalize_name(str(match.group("target")))
                if target.casefold() != killed_fold:
                    continue
                actor = cls._normalize_name(str(match.group(actor_group)))
                if actor and actor.casefold() != killed_fold:
                    opponents.add(actor)

        return opponents

    def _insert_colored_line(
        self,
        line: str,
        killed_name: str = "",
        opponent_names: Optional[set[str]] = None,
    ) -> None:
        """Insert one line with damage-type-aware coloring."""
        opponent_names = opponent_names or set()
        name_spans = self._collect_name_spans(line, killed_name, opponent_names)
        damage_spans = self._collect_color_spans(line)

        occupied_by_names = [(start, end) for start, end, _kind in name_spans]
        spans: list[tuple[int, int, str, str]] = []
        for start, end, kind in name_spans:
            spans.append((start, end, kind, "name"))
        for start, end, color_key in damage_spans:
            if self._spans_overlap(start, end, occupied_by_names):
                continue
            spans.append((start, end, color_key, "damage"))
        spans.sort(key=lambda item: (item[0], item[1]))

        if not spans:
            self.text.insert(tk.END, f"{line}\n")
            return

        cursor = 0
        for start, end, color_value, span_kind in spans:
            if start < cursor:
                continue
            if start > cursor:
                self.text.insert(tk.END, line[cursor:start])
            if span_kind == "name":
                if color_value == "killed":
                    tag_name = self._get_or_create_color_tag(self.KILLED_NAME_COLOR, "killed_name")
                else:
                    tag_name = self._get_or_create_color_tag(self.OPPONENT_NAME_COLOR, "opponent_name")
            else:
                tag_name = self._get_or_create_text_tag(color_value)
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

        lines = [self._sanitize_display_line(str(line)) for line in selected_event.get("lines", [])]
        display_lines = self._prepare_display_lines_for_wrap_mode(lines)
        killed_name = self._normalize_name(str(selected_event.get("target", "")))
        killer_name = self._normalize_name(str(selected_event.get("killer", "")))
        opponent_names = self._extract_opponent_names(lines, killed_name, killer_name)

        self.text.delete("1.0", tk.END)
        for line in display_lines:
            self._insert_colored_line(line, killed_name=killed_name, opponent_names=opponent_names)
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
