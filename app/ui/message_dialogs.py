"""Dark-mode modal dialogs for app-owned warning/error messages."""

import tkinter as tk
from tkinter import ttk
import webbrowser

from .tooltips import TooltipManager
from .window_style import apply_dark_title_bar


_DIALOG_BG = "#1c1c1c"
ABOUT_VERSION_TEXT = "Version 1.8.0"
ABOUT_DESCRIPTION_TEXT = (
    "A real-time combat log parser and DPS analyzer for Neverwinter Nights. "
    "Tracks DPS, target stats, immunities, and more from NWN game logs."
)
ADOH_URL = "https://www.adawnofheroes.org/"
RELEASES_URL = "https://github.com/synvanalt/woos-nwn-parser/releases/"


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


def show_about_dialog(parent: tk.Misc, *, icon_path: str | None = None) -> None:
    """Show the app About dialog."""
    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.configure(bg=_DIALOG_BG)
    dialog.title("About")
    dialog.resizable(False, False)
    dialog.transient(parent)
    _center_window_on_parent(parent, dialog, 520, 240)
    _apply_modal_icon(parent, dialog, icon_path)
    try:
        apply_dark_title_bar(dialog)
    except Exception:
        pass

    container = ttk.Frame(dialog, padding=16)
    container.pack(fill="both", expand=True)

    content = ttk.Frame(container)
    content.pack(fill="both", expand=True)
    tooltip_manager = TooltipManager(dialog)

    ttk.Label(
        content,
        text="Woo's NWN Parser",
        font=("", 12, "bold"),
    ).pack(anchor="w", fill="x")
    ttk.Label(
        content,
        text=ABOUT_VERSION_TEXT,
    ).pack(anchor="w", fill="x", pady=(6, 0))
    ttk.Label(
        content,
        text=ABOUT_DESCRIPTION_TEXT,
        justify="left",
        wraplength=480,
    ).pack(anchor="w", fill="x", pady=(12, 0))
    community_line = ttk.Frame(content)
    community_line.pack(anchor="w", fill="x", pady=(12, 0))
    ttk.Label(
        community_line,
        text="Built with love for the ",
    ).pack(side="left")
    adoh_link = ttk.Label(
        community_line,
        text="ADOH",
        foreground="#8ab4f8",
        cursor="hand2",
    )
    adoh_link.pack(side="left")
    adoh_link.bind(
        "<Button-1>",
        lambda _event: webbrowser.open_new_tab(ADOH_URL),
    )
    tooltip_manager.register(adoh_link, ADOH_URL)
    ttk.Label(
        community_line,
        text=" community.",
    ).pack(side="left")
    releases_line = ttk.Frame(content)
    releases_line.pack(anchor="w", fill="x", pady=(12, 0))
    ttk.Label(
        releases_line,
        text="Visit the ",
    ).pack(side="left")
    releases_link = ttk.Label(
        releases_line,
        text="GitHub Releases",
        foreground="#8ab4f8",
        cursor="hand2",
    )
    releases_link.pack(side="left")
    releases_link.bind(
        "<Button-1>",
        lambda _event: webbrowser.open_new_tab(RELEASES_URL),
    )
    tooltip_manager.register(releases_link, RELEASES_URL)
    ttk.Label(
        releases_line,
        text=" page for app updates.",
    ).pack(side="left")

    actions = ttk.Frame(container)
    actions.pack(side="bottom", fill="x")

    def _close(*_args: object) -> None:
        tooltip_manager.destroy()
        dialog.destroy()

    close_button = ttk.Button(actions, text="Close", command=_close)
    close_button.pack(anchor="e")

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
        close_button.focus_set()

    dialog.after_idle(_show_when_ready)
