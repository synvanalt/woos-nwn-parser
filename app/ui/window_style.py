"""Window styling helpers for Tkinter windows."""

import tkinter as tk
from ctypes import windll, byref, c_int, sizeof


def apply_dark_title_bar(window: tk.Tk | tk.Toplevel) -> None:
    """Force dark title bar on Windows 10/11."""
    window.update()

    dwmwa_use_immersive_dark_mode = 20
    set_window_attribute = windll.dwmapi.DwmSetWindowAttribute
    get_parent = windll.user32.GetParent
    hwnd = get_parent(window.winfo_id())

    value = c_int(2)
    set_window_attribute(
        hwnd,
        dwmwa_use_immersive_dark_mode,
        byref(value),
        sizeof(value)
    )
