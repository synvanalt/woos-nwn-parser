"""Death snippet panel widget for Woo's NWN Parser UI."""

from dataclasses import dataclass
from datetime import datetime
import tkinter as tk
from tkinter import ttk, font
from typing import Callable, Optional

from ...parsed_events import DeathSnippetEvent
from ..formatters import damage_type_to_color
from ..presenters import PreparedLine, format_death_event_dropdown_value, prepare_death_snippet_render
from ..tooltips import TooltipManager


@dataclass(slots=True)
class _DeathEventEntry:
    event: DeathSnippetEvent
    seq: int


class DeathSnippetPanel(ttk.Frame):
    """Panel for displaying death-related log snippets."""

    EMPTY_DROPDOWN_PLACEHOLDER = "Hurray! You have not died (yet)"
    EMPTY_TEXT_PLACEHOLDER = "Last 100 character-related log lines before death will appear here"
    CHARACTER_NAME_HINT = 'Whisper "wooparseme" in-game to auto-identify your character'
    DEFAULT_FALLBACK_DEATH_LINE = "Your God refuses to hear your prayers!"
    CONFIG_LABEL_WIDTH = 14
    KILLED_NAME_COLOR = "#98FEFF"
    OPPONENT_NAME_COLOR = "#CD98CC"

    def __init__(self, parent: ttk.Notebook, tooltip_manager: Optional[TooltipManager] = None) -> None:
        super().__init__(parent, padding="10")
        self._notebook = parent
        self.tooltip_manager = tooltip_manager
        self.death_events: list[_DeathEventEntry] = []
        self._event_sequence: int = 0
        self.killed_by_var = tk.StringVar(value=self.EMPTY_DROPDOWN_PLACEHOLDER)
        self.character_name_var = tk.StringVar(value="")
        self.fallback_death_line_var = tk.StringVar(value=self.DEFAULT_FALLBACK_DEATH_LINE)
        self.line_wrap_var = tk.BooleanVar(value=False)
        self._text_tags_by_color: dict[str, str] = {}
        self._last_render_key: Optional[tuple] = None
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
        self.character_name_label = ttk.Label(
            character_row,
            text="Character Name:",
            width=self.CONFIG_LABEL_WIDTH,
            anchor="w",
        )
        self.character_name_label.pack(side="left", padx=(0, 5))
        self.character_name_entry = ttk.Entry(
            character_row,
            textvariable=self.character_name_var,
        )
        self.character_name_entry.pack(side="left", fill="x", expand=True)
        self.clear_name_button = ttk.Button(
            character_row,
            text="Clear Name",
            command=self.clear_character_name,
        )
        self.clear_name_button.pack(side="left", padx=(8, 0))
        self.character_name_entry.bind("<FocusIn>", self._on_character_name_focus_in)
        self.character_name_entry.bind("<FocusOut>", self._on_character_name_focus_out)

        fallback_row = ttk.Frame(config_frame)
        fallback_row.pack(fill="x", pady=(0, 7))
        self.fallback_line_label = ttk.Label(
            fallback_row,
            text="Fallback Log Line:",
            width=self.CONFIG_LABEL_WIDTH,
            anchor="w",
        )
        self.fallback_line_label.pack(side="left", padx=(0, 5))
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

        self.killed_by_label = ttk.Label(
            selector_frame,
            text="Killed by:",
            width=self.CONFIG_LABEL_WIDTH,
            anchor="w",
        )
        self.killed_by_label.pack(side="left", padx=(0, 5))
        self.killed_by_combo = ttk.Combobox(
            selector_frame,
            state="disabled",
            width=40,
            textvariable=self.killed_by_var,
        )
        self.killed_by_combo.pack(side="left", fill="x", expand=True)
        self.killed_by_combo.bind("<<ComboboxSelected>>", _on_death_selected)

        self.line_wrap_toggle = ttk.Checkbutton(
            selector_frame,
            text="Line Wrap",
            variable=self.line_wrap_var,
            command=self._on_line_wrap_toggled,
        )
        self.line_wrap_toggle.pack(side="left", padx=(8, 0))

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
        self._register_tooltips()

    def _register_tooltips(self) -> None:
        """Register static tooltips for user-facing controls."""
        if self.tooltip_manager is None:
            return
        self.tooltip_manager.register_many(
            [self.character_name_label, self.character_name_entry],
            "Your character name for detection of death events",
        )
        self.tooltip_manager.register(
            self.clear_name_button,
            "Clear the saved character name and return to auto-detection or manual entry",
        )
        self.tooltip_manager.register_many(
            [self.fallback_line_label, self.fallback_death_line_entry],
            "Backup text used to detect your death when character name is left empty",
        )
        self.tooltip_manager.register_many(
            [self.killed_by_label, self.killed_by_combo],
            "Choose a recorded death event to display",
        )
        self.tooltip_manager.register(
            self.line_wrap_toggle,
            "Wrap long log lines to the panel width",
        )

    def _on_notebook_tab_changed(self, _event: tk.Event) -> None:
        """Set default focus to selector dropdown when entering this panel."""
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
        """Set the character-name entry foreground when the theme allows it."""
        try:
            self.character_name_entry.configure(foreground=color)
        except tk.TclError:
            pass

    def _set_fallback_entry_foreground(self, color: str) -> None:
        """Set the fallback-line entry foreground when the theme allows it."""
        try:
            self.fallback_death_line_entry.configure(foreground=color)
        except tk.TclError:
            pass

    def _set_combo_text_foreground(self, color: str) -> None:
        """Set dropdown text color when the theme allows it."""
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

    def clear_character_name(self) -> None:
        """Clear the assigned character name and restore the hint state."""
        self.set_character_name("")

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

    def _show_placeholder(self) -> None:
        """Show default text when there are no death snippets."""
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", self.EMPTY_TEXT_PLACEHOLDER)
        self._last_render_key = None

    @staticmethod
    def _event_sort_timestamp(entry: _DeathEventEntry) -> datetime:
        """Return event timestamp for sorting, with safe fallback."""
        timestamp = entry.event.timestamp
        return timestamp if isinstance(timestamp, datetime) else datetime.min

    @staticmethod
    def _format_dropdown_value(entry: _DeathEventEntry) -> str:
        """Build dropdown value text as HH:MM:SS plus original killer name."""
        return format_death_event_dropdown_value(entry.event.timestamp, entry.event.killer)

    def _set_combo_values(self) -> None:
        """Refresh combobox values from current death events."""
        values = [self._format_dropdown_value(entry) for entry in self.death_events]
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

    def _get_selected_event(self) -> Optional[_DeathEventEntry]:
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

    def _insert_prepared_line(self, prepared_line: PreparedLine) -> None:
        """Insert one precomputed line with widget tag mapping."""
        if not prepared_line.spans:
            self.text.insert(tk.END, f"{prepared_line.text}\n")
            return

        cursor = 0
        for span in prepared_line.spans:
            if span.start < cursor:
                continue
            if span.start > cursor:
                self.text.insert(tk.END, prepared_line.text[cursor:span.start])
            if span.kind == "name":
                if span.value == "killed":
                    tag_name = self._get_or_create_color_tag(self.KILLED_NAME_COLOR, "killed_name")
                else:
                    tag_name = self._get_or_create_color_tag(self.OPPONENT_NAME_COLOR, "opponent_name")
            else:
                tag_name = self._get_or_create_text_tag(span.value)
            self.text.insert(tk.END, prepared_line.text[span.start:span.end], tag_name)
            cursor = span.end

        if cursor < len(prepared_line.text):
            self.text.insert(tk.END, prepared_line.text[cursor:])
        self.text.insert(tk.END, "\n")

    def render_selected_event(self) -> None:
        """Render snippet lines for the currently selected death event."""
        selected_event = self._get_selected_event()
        if selected_event is None:
            self._show_placeholder()
            return

        selected_index = self.killed_by_combo.current()
        selected_seq = selected_event.seq
        render_key = (selected_index, selected_seq)
        if render_key == self._last_render_key:
            return

        measure_text = getattr(self.theme_font, "measure", None) if hasattr(self, "theme_font") else None
        prepared_render = prepare_death_snippet_render(
            selected_event.event,
            wrap_lines=bool(self.line_wrap_var.get()),
            measure_text=measure_text,
        )

        self.text.delete("1.0", tk.END)
        for prepared_line in prepared_render.lines:
            self._insert_prepared_line(prepared_line)
        self.text.see(tk.END)
        self._last_render_key = render_key

    def add_death_event(self, event: DeathSnippetEvent) -> None:
        """Add a death snippet event and select newest entry."""
        self.add_death_events([event])

    def add_death_events(self, events: list[DeathSnippetEvent]) -> None:
        """Add one or more death snippet events and select the newest entry."""
        added = False
        for event in events:
            lines = event.lines or []
            if not lines:
                continue

            self.death_events.append(_DeathEventEntry(event=event, seq=self._event_sequence))
            self._event_sequence += 1
            added = True

        if not added:
            return

        self.death_events.sort(
            key=lambda item: (self._event_sort_timestamp(item), item.seq),
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
