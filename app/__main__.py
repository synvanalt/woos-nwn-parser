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


def fix_treeview_indicator(root: tk.Tk) -> None:
    """Fix the sv_ttk treeview indicator to properly show open/closed states.

    The sv_ttk theme creates a custom Treeitem.indicator image element that uses
    'user1' state instead of the Treeview's internal open/close mechanism.
    This breaks the expand/collapse arrows.

    The fix: Remove sv_ttk's broken indicator from the layout and use the item's
    image property instead. We also provide a helper function that treeview widgets
    can use to set up proper click handling and image updates.
    """
    # Get sv_ttk's arrow images for later use
    try:
        down_img = root.tk.eval("set ::ttk::theme::sv_dark::I(down)")
        right_img = root.tk.eval("set ::ttk::theme::sv_dark::I(right)")
    except tk.TclError:
        # If we can't get the images, skip the fix
        return

    # Remove the broken indicator from layout - we'll use item image instead
    try:
        root.tk.eval('''
            ttk::style layout Treeview.Item {
                Treeitem.padding -sticky nswe -children {
                    Treeitem.image -sticky nswe -sticky {}
                    Treeitem.text -sticky nswe
                }
            }
        ''')
    except tk.TclError:
        return

    # Store image references and helper function on root for treeviews to use
    root._sv_ttk_down_img = down_img
    root._sv_ttk_right_img = right_img

    def bind_treeview_indicator_fix(tree) -> None:
        """Bind a treeview to properly show sv_ttk indicator arrows.

        Args:
            tree: A ttk.Treeview widget
        """
        def update_all_indicators() -> None:
            """Update indicator images for all parent items."""
            for item in tree.get_children():
                if tree.get_children(item):
                    img = down_img if tree.item(item, "open") else right_img
                    tree.item(item, image=img)

        def on_click(event):
            """Handle single-click to toggle expand/collapse on tree column."""
            if tree.identify_region(event.x, event.y) == "tree":
                item = tree.identify_row(event.y)
                if item and tree.get_children(item):
                    # Toggle open state and update image to match NEW state
                    will_be_open = not tree.item(item, "open")
                    tree.item(item, open=will_be_open, image=down_img if will_be_open else right_img)
                    return "break"
            return None

        def on_open(event) -> None:
            """Handle open event - update the focused item's indicator."""
            item = tree.focus()
            if item:
                tree.item(item, image=down_img)

        def on_close(event) -> None:
            """Handle close event - update the focused item's indicator."""
            item = tree.focus()
            if item:
                tree.item(item, image=right_img)

        tree.bind("<Button-1>", on_click, add=True)
        tree.bind("<<TreeviewOpen>>", on_open, add=True)
        tree.bind("<<TreeviewClose>>", on_close, add=True)

        # Store update function on tree for manual refresh calls
        tree._update_indicators = update_all_indicators

        # Initial update
        update_all_indicators()

    root._fix_treeview_indicator = bind_treeview_indicator_fix


def main() -> None:
    """Launch Woo's NWN Parser application."""
    root = tk.Tk()
    sv_ttk.set_theme("dark")

    # Fix the treeview indicator to properly show expand/collapse arrows
    fix_treeview_indicator(root)

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

