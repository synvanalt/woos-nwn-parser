"""Main entry point for Woo's NWN Parser application."""

import sys
import tkinter as tk
from pathlib import Path

import sv_ttk
from ctypes import windll, byref, c_int, sizeof

from app.ui import WoosNwnParserApp


def get_resource_path(relative_path: str) -> Path:
    """
    Get absolute path to resource, works for dev and for PyInstaller.

    When running in a PyInstaller bundle, files are extracted to a temp folder
    referenced by sys._MEIPASS. In development, we use the script's directory.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        # Running in development mode
        base_path = Path(__file__).parent.parent

    return base_path / relative_path


def apply_dark_title_bar(window):
    """
    Forces the Windows title bar to use dark mode (Windows 10/11).
    Works without refreshing or restarting the app.
    """
    window.update()  # Force internal window structures to be created

    # Constants for Windows API
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20

    # 1. Get the window handle (HWND)
    # Tkinter's winfo_id() returns the handle of the inner content area.
    # We need the parent wrapper (the actual OS window).
    set_window_attribute = windll.dwmapi.DwmSetWindowAttribute
    get_parent = windll.user32.GetParent
    hwnd = get_parent(window.winfo_id())

    # 2. Set the Dark Mode Attribute
    # value 2 = True (Enable Dark Mode), value 0 = False (Disable)
    rendering_policy = DWMWA_USE_IMMERSIVE_DARK_MODE
    value = c_int(2)

    # 3. Apply the change via DwmSetWindowAttribute
    set_window_attribute(
        hwnd,
        rendering_policy,
        byref(value),
        sizeof(value)
    )


def main() -> None:
    """Launch Woo's NWN Parser application."""
    root = tk.Tk()
    sv_ttk.set_theme("dark")


    app = WoosNwnParserApp(root)

    # Set window icon (works in both dev and bundled exe)
    icon_path = get_resource_path("app/assets/icons/ir_attack.ico")
    if icon_path.exists():
        root.iconbitmap(str(icon_path))

    root.protocol("WM_DELETE_WINDOW", app.on_closing)

    # Apply the dark title bar
    try:
        apply_dark_title_bar(root)
    except Exception as e:
        print(f"Failed to apply dark title bar: {e}")

    root.mainloop()


if __name__ == "__main__":
    main()

