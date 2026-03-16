"""Dark-mode modal dialogs for app-owned warning/error messages."""

import tkinter as tk
from tkinter import ttk

from .window_style import apply_dark_title_bar


_DIALOG_BG = "#1c1c1c"


def _center_window_on_parent(
    parent: tk.Misc,
    window: tk.Toplevel,
    width: int,
    height: int,
) -> None:
    """Center a child dialog relative to its parent window."""
    parent.update_idletasks()
    root_x = parent.winfo_rootx()
    root_y = parent.winfo_rooty()
    root_w = parent.winfo_width()
    root_h = parent.winfo_height()

    x = max(0, root_x + (root_w - width) // 2)
    y = max(0, root_y + (root_h - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def _apply_modal_icon(
    parent: tk.Misc,
    window: tk.Toplevel,
    icon_path: str | None,
) -> None:
    """Apply the same icon used by the main app window when available."""
    if icon_path:
        try:
            window.iconbitmap(icon_path)
            return
        except Exception:
            pass

    try:
        icon_ref = parent.iconbitmap()
        if icon_ref:
            window.iconbitmap(icon_ref)
    except Exception:
        pass


def _show_dialog(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    icon_path: str | None = None,
) -> None:
    """Show a dark themed acknowledgement dialog."""
    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.configure(bg=_DIALOG_BG)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.transient(parent)
    _center_window_on_parent(parent, dialog, 460, 140)
    _apply_modal_icon(parent, dialog, icon_path)
    try:
        apply_dark_title_bar(dialog)
    except Exception:
        pass

    container = ttk.Frame(dialog, padding=16)
    container.pack(fill="both", expand=True)

    ttk.Label(
        container,
        text=message,
        justify="left",
        wraplength=420,
    ).pack(anchor="w", fill="x")

    actions = ttk.Frame(container)
    actions.pack(side="bottom", fill="x")

    def _close(*_args: object) -> None:
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        dialog.destroy()

    ok_button = ttk.Button(actions, text="OK", command=_close)
    ok_button.pack(anchor="e")

    dialog.protocol("WM_DELETE_WINDOW", _close)
    dialog.bind("<Return>", _close)
    dialog.bind("<Escape>", _close)

    try:
        dialog.attributes("-alpha", 0.0)
    except tk.TclError:
        pass

    def _show_when_ready() -> None:
        dialog.update_idletasks()
        dialog.deiconify()
        dialog.lift()
        try:
            dialog.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        dialog.grab_set()
        ok_button.focus_set()

    dialog.after_idle(_show_when_ready)
    parent.wait_window(dialog)


def show_warning_dialog(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    icon_path: str | None = None,
) -> None:
    """Show a warning dialog using the app dark theme."""
    _show_dialog(parent, title, message, icon_path=icon_path)


def show_error_dialog(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    icon_path: str | None = None,
) -> None:
    """Show an error dialog using the app dark theme."""
    _show_dialog(parent, title, message, icon_path=icon_path)
