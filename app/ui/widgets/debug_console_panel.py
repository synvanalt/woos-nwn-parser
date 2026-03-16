"""Debug console panel widget for Woo's NWN Parser UI.

This module contains the DebugConsolePanel widget that displays debug
messages with color-coded logging levels.
"""

import tkinter as tk
from tkinter import ttk, font
from typing import Optional

from ..tooltips import TooltipManager


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
        tooltip_manager: Optional[TooltipManager] = None,
    ) -> None:
        """Initialize the debug console panel.

        Args:
            parent: Parent notebook widget
        """
        super().__init__(parent, padding="10")
        self.tooltip_manager = tooltip_manager
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
        debug_controls_frame.pack(fill="x", padx=(10, 10), pady=(0, 10))

        # Debug Switcher to enable/disable debug output
        self.debug_output_toggle = ttk.Checkbutton(
            debug_controls_frame,
            text="Debug Output",
            variable=self.debug_mode_var,
            style="Switch.TCheckbutton",
        )
        self.debug_output_toggle.pack(side="left", padx=0, pady=0)

        # Clear debug button
        self.clear_debug_button = ttk.Button(debug_controls_frame, text="Clear Debug Log", command=self.clear)
        self.clear_debug_button.pack(side="right", pady=0)

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
        self._register_tooltips()

    def _register_tooltips(self) -> None:
        """Register static tooltips for user-facing controls."""
        if self.tooltip_manager is None:
            return
        self.tooltip_manager.register(
            self.debug_output_toggle,
            "Show diagnostic messages from the app, including monitor and parser status information",
        )
        self.tooltip_manager.register(
            self.clear_debug_button,
            "Clear the current debug console contents",
        )

    def log(self, message: str, msg_type: str = "debug") -> None:
        """Add a message to the debug console.

        Args:
            message: Message to add
            msg_type: Type of message ('info', 'debug', 'warning', 'error')
        """
        if self.debug_mode_var.get():
            from datetime import datetime

            # Check if the scrollbar is currently at the very bottom
            # yview() returns a tuple like (0.0, 1.0)
            # The second value [1] is the position of the bottom of the view
            current_scroll_pos = self.text.yview()
            at_bottom = current_scroll_pos[1] == 1.0

            timestamp = datetime.now().strftime("%H:%M:%S")
            self.text.insert(tk.END, f"[{timestamp}] {message}\n", msg_type)

            # Only scroll to the end if the user was already at the bottom
            if at_bottom:
                self.text.see(tk.END)

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

