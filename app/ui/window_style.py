"""Window styling helpers for Tkinter windows."""

import tkinter as tk
import ctypes


def apply_dark_title_bar(window: tk.Tk | tk.Toplevel) -> None:
    """Force dark title bar on Windows 10/11."""
    if not hasattr(ctypes, "windll"):
        return

    window.update()

    dwmwa_use_immersive_dark_mode = 20
    set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
    get_parent = ctypes.windll.user32.GetParent
    hwnd = get_parent(window.winfo_id())

    value = ctypes.c_int(2)
    set_window_attribute(
        hwnd,
        dwmwa_use_immersive_dark_mode,
        ctypes.byref(value),
        ctypes.sizeof(value)
    )
