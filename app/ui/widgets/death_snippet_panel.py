"""Death snippet panel widget for Woo's NWN Parser UI."""

import re
from datetime import datetime
import tkinter as tk
from tkinter import ttk, font
from typing import Any, Dict, List, Optional


class DeathSnippetPanel(ttk.Frame):
    """Panel for displaying death-related log snippets."""

    EMPTY_PLACEHOLDER = "Hurray! You have not died (yet)"

    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(parent, padding="10")
        self.death_events: List[Dict[str, Any]] = []
        self._event_sequence: int = 0

        try:
            self.theme_font = font.nametofont("SunValleyBodyFont")
        except tk.TclError:
            self.theme_font = font.Font(family="Courier", size=10)

        self.setup_ui()
        self._show_placeholder()

    def setup_ui(self) -> None:
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=(10, 10), pady=(8, 6))

        ttk.Label(
            controls,
            text="Last 100 character-related lines before each death",
        ).pack(side="left")
        ttk.Button(
            controls,
            text="Clear Death Snippets",
            command=self.clear,
        ).pack(side="right")

        selector_frame = ttk.Frame(self)
        selector_frame.pack(fill="x", padx=(10, 10), pady=(0, 10))

        def _on_death_selected(_event: tk.Event) -> None:
            self.render_selected_event()

        self.killed_by_combo = ttk.Combobox(selector_frame, state="disabled", width=40)
        self.killed_by_combo.pack(side="right", padx=5, fill="x", expand=False)
        self.killed_by_combo.bind("<<ComboboxSelected>>", _on_death_selected)
        ttk.Label(selector_frame, text="Killed by").pack(side="right", padx=5)

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
        self.text.insert("1.0", self.EMPTY_PLACEHOLDER)

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
            self.killed_by_combo.configure(state="disabled")
            self.killed_by_combo.set("")

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

    def render_selected_event(self) -> None:
        """Render snippet lines for the currently selected death event."""
        selected_event = self._get_selected_event()
        if selected_event is None:
            self._show_placeholder()
            return

        lines = selected_event.get("lines", [])
        self.text.delete("1.0", tk.END)
        for line in lines:
            self.text.insert(tk.END, f"{self._sanitize_display_line(str(line))}\n")
        self.text.see(tk.END)

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
        if self.death_events:
            self.killed_by_combo.current(0)
            self.render_selected_event()

    def append_snippet(self, lines: List[str]) -> None:
        """Backward-compatible line-only insertion for death snippet events."""
        self.add_death_event({"lines": lines, "killer": "", "timestamp": None, "target": ""})

    def clear(self) -> None:
        """Clear all recorded death snippets."""
        self.death_events.clear()
        self._event_sequence = 0
        self._set_combo_values()
        self._show_placeholder()
