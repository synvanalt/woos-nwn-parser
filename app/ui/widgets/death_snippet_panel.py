"""Death snippet panel widget for Woo's NWN Parser UI."""

import re
import tkinter as tk
from tkinter import ttk, font
from typing import List


class DeathSnippetPanel(ttk.Frame):
    """Panel for displaying death-related log snippets."""

    EMPTY_PLACEHOLDER = "Hurray! You have not died (yet)."

    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(parent, padding="10")

        try:
            self.theme_font = font.nametofont("SunValleyBodyFont")
        except tk.TclError:
            self.theme_font = font.Font(family="Courier", size=10)

        self.setup_ui()
        self._show_placeholder()

    def setup_ui(self) -> None:
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=(10, 10), pady=(8, 10))

        ttk.Label(
            controls,
            text="Last 100 character-related lines before each death",
        ).pack(side="left")
        ttk.Button(
            controls,
            text="Clear Death Snippets",
            command=self.clear,
        ).pack(side="right")

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

    def _is_showing_placeholder(self) -> bool:
        """Check whether the panel currently shows only the placeholder text."""
        return self.text.get("1.0", "end-1c") == self.EMPTY_PLACEHOLDER

    def append_snippet(self, lines: List[str]) -> None:
        """Append one death snippet block and keep view at the bottom."""
        if not lines:
            return

        if self._is_showing_placeholder():
            self.text.delete("1.0", tk.END)
            has_existing = False
        else:
            has_existing = bool(self.text.index("end-1c") != "1.0")

        if has_existing:
            self.text.insert(tk.END, f"\n\n\n▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀\n\n\n\n")

        for line in lines:
            self.text.insert(tk.END, f"{self._sanitize_display_line(line)}\n")

        self.text.see(tk.END)

    def clear(self) -> None:
        """Clear all recorded death snippets."""
        self._show_placeholder()
