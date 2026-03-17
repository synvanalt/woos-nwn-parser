"""Shared tooltip helpers for Tkinter UI widgets."""

from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import font
from typing import Optional
import weakref


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
        self._specs: weakref.WeakKeyDictionary[tk.Misc, TooltipSpec] = weakref.WeakKeyDictionary()
        self._tagged_widgets: weakref.WeakSet[tk.Misc] = weakref.WeakSet()
        self._popup: Optional[tk.Toplevel] = None
        self._label: Optional[tk.Label] = None
        self._pending_widget: Optional[tk.Misc] = None
        self._active_widget: Optional[tk.Misc] = None
        self._show_job = None
        self._bindtag = f"TooltipTarget_{id(self)}"
        self._class_sequences = ("<Enter>", "<Leave>", "<ButtonPress>")
        self._popup_bind_ids: dict[str, str] = {}
        self._install_bindtag_handlers()

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
        bindtags = widget.bindtags()
        if self._bindtag not in bindtags:
            widget.bindtags((self._bindtag, *bindtags))
        self._tagged_widgets.add(widget)

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
        self._specs.pop(widget, None)
        self._remove_bindtag(widget)
        if self._active_widget is widget or self._pending_widget is widget:
            self.hide()

    def destroy(self) -> None:
        """Release tooltip resources before the host toplevel is destroyed."""
        self.hide()
        self._specs.clear()
        self._remove_all_bindtags()
        self._unbind_class_handlers()
        popup = self._popup
        self._popup = None
        self._label = None
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass

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

    def _on_enter(self, event: tk.Event) -> None:
        widget = self._coerce_widget(getattr(event, "widget", None))
        if widget is None:
            return
        spec = self._specs.get(widget)
        if spec is None or not spec.text:
            return
        self._cancel_show_job()
        self._pending_widget = widget
        self._show_job = self.host.after(spec.delay_ms, lambda w=widget, x=event.x_root, y=event.y_root: self._show(w, x, y))

    def _on_leave(self, event: tk.Event) -> None:
        widget = self._coerce_widget(getattr(event, "widget", None))
        if widget is None:
            return
        if self._pending_widget is widget or self._active_widget is widget:
            self.hide()

    def _on_popup_dismiss(self, _event: tk.Event) -> None:
        self.hide()

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
        self._popup_bind_ids = {
            "<FocusOut>": popup.bind("<FocusOut>", self._on_popup_dismiss, add=True),
            "<Unmap>": popup.bind("<Unmap>", self._on_popup_dismiss, add=True),
        }
        self._popup = popup
        self._label = label

    def _install_bindtag_handlers(self) -> None:
        """Bind shared event handlers for the tooltip bindtag."""
        self.host.bind_class(self._bindtag, "<Enter>", self._on_enter)
        self.host.bind_class(self._bindtag, "<Leave>", self._on_leave)
        self.host.bind_class(self._bindtag, "<ButtonPress>", self._on_leave)

    def _unbind_class_handlers(self) -> None:
        """Remove manager-owned shared class bindings."""
        for sequence in self._class_sequences:
            try:
                self.host.bind_class(self._bindtag, sequence, "")
            except tk.TclError:
                pass

    def _remove_bindtag(self, widget: tk.Misc) -> None:
        """Remove the tooltip bindtag from a widget if it still exists."""
        try:
            bindtags = tuple(tag for tag in widget.bindtags() if tag != self._bindtag)
            widget.bindtags(bindtags)
        except tk.TclError:
            pass
        try:
            self._tagged_widgets.discard(widget)
        except TypeError:
            pass

    def _remove_all_bindtags(self) -> None:
        """Detach the tooltip bindtag from all still-live widgets."""
        for widget in list(self._tagged_widgets):
            self._remove_bindtag(widget)

    @staticmethod
    def _coerce_widget(widget: object) -> Optional[tk.Misc]:
        """Return a Tk widget object when the event target is usable."""
        if isinstance(widget, tk.Misc):
            return widget
        return None

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

    def _show(self, widget: tk.Misc, x_root: int, y_root: int) -> None:
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
        x = int(x_root) + spec.offset_x
        y = int(y_root) + spec.offset_y
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
