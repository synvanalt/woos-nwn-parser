"""Unit tests for the shared Tk tooltip helper."""

import tkinter as tk

import pytest
import sv_ttk

from app.ui.main_window import WoosNwnParserApp
from app.ui.tooltips import TooltipManager


@pytest.fixture
def managed_widget(shared_tk_root):
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")
    widget = tk.Label(shared_tk_root, text="hover me")
    widget.pack()
    yield widget
    try:
        widget.destroy()
    except tk.TclError:
        pass


def test_register_overwrites_existing_binding_state(managed_widget) -> None:
    manager = TooltipManager(managed_widget.winfo_toplevel())
    original_bindtags = managed_widget.bindtags()

    manager.register(managed_widget, "first")
    first_commands = list(getattr(managed_widget, "_tclCommands", []) or [])

    manager.register(managed_widget, "second")

    assert manager._specs[managed_widget].text == "second"
    assert managed_widget.bindtags().count(manager._bindtag) == 1
    assert getattr(managed_widget, "_tclCommands", []) == first_commands
    assert managed_widget.bindtags()[1:] == original_bindtags


def test_show_and_hide_reuse_single_popup(managed_widget) -> None:
    manager = TooltipManager(managed_widget.winfo_toplevel())
    manager.register(managed_widget, "tooltip text", delay_ms=0)
    enter_event = tk.Event()
    enter_event.x_root = 20
    enter_event.y_root = 30

    enter_event.widget = managed_widget

    manager._on_enter(enter_event)
    manager._show(managed_widget, enter_event.x_root, enter_event.y_root)

    assert manager._popup is not None
    first_popup = manager._popup
    assert manager._active_widget is managed_widget

    manager.hide()

    assert manager._active_widget is None
    assert manager._popup is first_popup


def test_unregister_clears_registered_tooltip(managed_widget) -> None:
    manager = TooltipManager(managed_widget.winfo_toplevel())
    original_bindtags = managed_widget.bindtags()
    manager.register(managed_widget, "tooltip text")

    manager.unregister(managed_widget)

    assert managed_widget not in manager._specs
    assert manager._bindtag not in managed_widget.bindtags()
    assert managed_widget.bindtags() == original_bindtags


def test_register_does_not_add_widget_specific_tcl_commands(managed_widget) -> None:
    manager = TooltipManager(managed_widget.winfo_toplevel())
    before_commands = list(getattr(managed_widget, "_tclCommands", []) or [])

    manager.register(managed_widget, "tooltip text")

    assert list(getattr(managed_widget, "_tclCommands", []) or []) == before_commands


def test_mapped_app_with_visible_tooltip_closes_cleanly() -> None:
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available")

    try:
        root.configure(bg="#1c1c1c")
        sv_ttk.set_theme("dark")
        app = WoosNwnParserApp(root)
        event = tk.Event()
        event.widget = app.browse_button
        event.x_root = 80
        event.y_root = 90
        app.tooltip_manager._on_enter(event)
        app.tooltip_manager._show(app.browse_button, event.x_root, event.y_root)
        root.update_idletasks()
        root.update()

        app.on_closing()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
