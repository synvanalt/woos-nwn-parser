"""Shared tooltip helpers for Tkinter UI widgets."""

from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import font
from typing import Optional


@dataclass(frozen=True)
class TooltipSpec:
    """Static tooltip configuration for one widget."""

    text: str
    delay_ms: int = 450
    wraplength: int = 360
    offset_x: int = 14
    offset_y: int = 18


class TooltipManager:
    """Manage a shared tooltip popup for widgets within one toplevel."""

    def __init__(self, host: tk.Misc) -> None:
        self.host = host
        self._specs: dict[tk.Misc, TooltipSpec] = {}
        self._bind_ids: dict[tk.Misc, dict[str, str]] = {}
        self._popup: Optional[tk.Toplevel] = None
        self._label: Optional[tk.Label] = None
        self._pending_widget: Optional[tk.Misc] = None
        self._active_widget: Optional[tk.Misc] = None
        self._show_job = None

    def register(
        self,
        widget: tk.Misc,
        text: str,
        *,
        delay_ms: Optional[int] = None,
        wraplength: Optional[int] = None,
    ) -> None:
        """Register a static tooltip for a widget."""
        self.unregister(widget)
        spec = TooltipSpec(
            text=str(text),
            delay_ms=TooltipSpec.delay_ms if delay_ms is None else int(delay_ms),
            wraplength=TooltipSpec.wraplength if wraplength is None else int(wraplength),
        )
        self._specs[widget] = spec
        self._bind_ids[widget] = {
            "<Enter>": widget.bind("<Enter>", lambda event, w=widget: self._on_enter(w, event), add=True),
            "<Leave>": widget.bind("<Leave>", lambda event, w=widget: self._on_leave(w, event), add=True),
            "<ButtonPress>": widget.bind("<ButtonPress>", lambda event, w=widget: self._on_leave(w, event), add=True),
            "<Destroy>": widget.bind("<Destroy>", lambda event, w=widget: self._on_destroy(w, event), add=True),
        }

    def register_many(
        self,
        widgets: list[tk.Misc] | tuple[tk.Misc, ...],
        text: str,
        *,
        delay_ms: Optional[int] = None,
        wraplength: Optional[int] = None,
    ) -> None:
        """Register the same tooltip for multiple widgets."""
        for widget in widgets:
            self.register(widget, text, delay_ms=delay_ms, wraplength=wraplength)

    def unregister(self, widget: tk.Misc) -> None:
        """Remove tooltip bindings and metadata for a widget."""
        bind_ids = self._bind_ids.pop(widget, {})
        for sequence, bind_id in bind_ids.items():
            try:
                widget.unbind(sequence, bind_id)
            except tk.TclError:
                pass
        self._specs.pop(widget, None)
        if self._active_widget is widget or self._pending_widget is widget:
            self.hide()

    def hide(self) -> None:
        """Hide the tooltip popup and clear active state."""
        self._cancel_show_job()
        self._pending_widget = None
        self._active_widget = None
        if self._popup is not None:
            try:
                self._popup.withdraw()
            except tk.TclError:
                pass

    def _on_enter(self, widget: tk.Misc, event: tk.Event) -> None:
        spec = self._specs.get(widget)
        if spec is None or not spec.text:
            return
        self._cancel_show_job()
        self._pending_widget = widget
        self._show_job = widget.after(spec.delay_ms, lambda w=widget, e=event: self._show(w, e))

    def _on_leave(self, widget: tk.Misc, _event: tk.Event) -> None:
        if self._pending_widget is widget or self._active_widget is widget:
            self.hide()

    def _on_destroy(self, widget: tk.Misc, _event: tk.Event) -> None:
        self.unregister(widget)

    def _cancel_show_job(self) -> None:
        if self._show_job is None:
            return
        try:
            self.host.after_cancel(self._show_job)
        except tk.TclError:
            pass
        self._show_job = None

    def _ensure_popup(self) -> None:
        if self._popup is not None and self._label is not None:
            return
        border_color = self._resolve_outline_color()
        popup = tk.Toplevel(self.host)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.configure(bg=border_color, padx=1, pady=1)
        try:
            popup.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            tooltip_font = font.nametofont("SunValleyBodyFont")
        except tk.TclError:
            tooltip_font = font.Font(family="Segoe UI", size=10)
        label = tk.Label(
            popup,
            bg="#2a2a2a",
            fg="#f2f2f2",
            relief="flat",
            justify="left",
            anchor="w",
            padx=8,
            pady=5,
            font=tooltip_font,
        )
        label.pack(fill="both", expand=True)
        popup.bind("<FocusOut>", lambda _event: self.hide(), add=True)
        popup.bind("<Unmap>", lambda _event: self.hide(), add=True)
        self._popup = popup
        self._label = label

    def _resolve_outline_color(self) -> str:
        """Return a muted border color from the active Sun Valley dark theme."""
        tk_app = getattr(self.host, "tk", None)
        if tk_app is not None:
            for expr in (
                "set ::ttk::theme::sv_dark::colors(-disfg)",
                "ttk::style lookup TEntry -foreground disabled",
            ):
                try:
                    value = str(tk_app.eval(expr)).strip()
                except tk.TclError:
                    continue
                if value:
                    return value
        return "#7a7a7a"

    def _show(self, widget: tk.Misc, event: tk.Event) -> None:
        self._show_job = None
        if self._pending_widget is not widget:
            return
        spec = self._specs.get(widget)
        if spec is None or not widget.winfo_exists():
            return
        self._ensure_popup()
        if self._popup is None or self._label is None:
            return
        self._label.configure(text=spec.text, wraplength=spec.wraplength)
        x = int(event.x_root) + spec.offset_x
        y = int(event.y_root) + spec.offset_y
        self._popup.update_idletasks()
        width = self._popup.winfo_reqwidth()
        height = self._popup.winfo_reqheight()
        screen_width = self._popup.winfo_screenwidth()
        screen_height = self._popup.winfo_screenheight()
        x = min(max(0, x), max(0, screen_width - width))
        y = min(max(0, y), max(0, screen_height - height))
        self._popup.geometry(f"+{x}+{y}")
        self._popup.deiconify()
        self._active_widget = widget
        self._pending_widget = None
