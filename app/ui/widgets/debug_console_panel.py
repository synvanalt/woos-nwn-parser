"""Debug console panel widget for Woo's NWN Parser UI.

This module contains the DebugConsolePanel widget that displays debug
messages with color-coded logging levels.
"""

import tkinter as tk
from tkinter import ttk, font


class DebugConsolePanel(ttk.Frame):
    """Debug console display panel.

    Manages:
    - Text widget for displaying debug output
    - Color-coded message types (info, debug, warning, error)
    - Debug mode toggle checkbox
    - Clear debug log button

    This is a reusable widget that can be placed in any notebook or frame.
    """

    def __init__(
        self,
        parent: ttk.Notebook,
    ) -> None:
        """Initialize the debug console panel.

        Args:
            parent: Parent notebook widget
        """
        super().__init__(parent, padding="10")
        self.debug_mode_var = tk.BooleanVar(value=False)

        # Get theme font
        try:
            self.theme_font = font.nametofont("SunValleyBodyFont")
        except tk.TclError:
            self.theme_font = font.Font(family="Courier", size=10)

        self.setup_ui()

    def setup_ui(self) -> None:
        """Setup the panel UI components."""
        # Debug output switcher
        debug_controls_frame = ttk.Frame(self)
        debug_controls_frame.pack(fill="x", padx=(10, 10), pady=(10, 10))

        # Debug Switcher to enable/disable debug output
        ttk.Checkbutton(
            debug_controls_frame,
            text="Debug Output",
            variable=self.debug_mode_var,
            style="Switch.TCheckbutton",
        ).pack(side="left", padx=0, pady=0)

        # Debug text widget with scrollbar
        debug_scroll = ttk.Scrollbar(self)
        debug_scroll.pack(side="right", fill="y")

        self.text = tk.Text(
            self,
            font=self.theme_font,
            wrap="word",
            yscrollcommand=debug_scroll.set,
            height=30,
        )
        self.text.pack(fill="both", expand=True)

        # Configure the tags with different colors
        self.text.tag_configure("info", foreground="white")  # Default
        self.text.tag_configure("debug", foreground="gray")  # Debug lines
        self.text.tag_configure("warning", foreground="orange")  # Warnings
        self.text.tag_configure("error", foreground="red")  # Errors

        debug_scroll.config(command=self.text.yview)

        # Clear debug button
        ttk.Button(self, text="Clear Debug Log", command=self.clear).pack(pady=5)

    def log(self, message: str, msg_type: str = "debug") -> None:
        """Add a message to the debug console.

        Args:
            message: Message to add
            msg_type: Type of message ('info', 'debug', 'warning', 'error')
        """
        if self.debug_mode_var.get():
            from datetime import datetime

            timestamp = datetime.now().strftime("%H:%M:%S")
            self.text.insert(tk.END, f"[{timestamp}] {message}\n", msg_type)
            self.text.see(tk.END)  # Auto-scroll to bottom

    def clear(self) -> None:
        """Clear the debug console."""
        self.text.delete(1.0, tk.END)

    def get_debug_enabled(self) -> bool:
        """Check if debug output is enabled.

        Returns:
            True if debug mode is enabled
        """
        return bool(self.debug_mode_var.get())

    def set_debug_enabled(self, enabled: bool) -> None:
        """Set debug enabled state.

        Args:
            enabled: True to enable debug output
        """
        self.debug_mode_var.set(enabled)

