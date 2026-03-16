"""Unit tests for the shared Tk tooltip helper."""

import tkinter as tk

import pytest

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

    manager.register(managed_widget, "first")
    first_bind_ids = dict(manager._bind_ids[managed_widget])

    manager.register(managed_widget, "second")

    assert manager._specs[managed_widget].text == "second"
    assert set(manager._bind_ids[managed_widget]) == set(first_bind_ids)


def test_show_and_hide_reuse_single_popup(managed_widget) -> None:
    manager = TooltipManager(managed_widget.winfo_toplevel())
    manager.register(managed_widget, "tooltip text", delay_ms=0)
    enter_event = tk.Event()
    enter_event.x_root = 20
    enter_event.y_root = 30

    manager._on_enter(managed_widget, enter_event)
    manager._show(managed_widget, enter_event)

    assert manager._popup is not None
    first_popup = manager._popup
    assert manager._active_widget is managed_widget

    manager.hide()

    assert manager._active_widget is None
    assert manager._popup is first_popup


def test_unregister_clears_registered_tooltip(managed_widget) -> None:
    manager = TooltipManager(managed_widget.winfo_toplevel())
    manager.register(managed_widget, "tooltip text")

    manager.unregister(managed_widget)

    assert managed_widget not in manager._specs
    assert managed_widget not in manager._bind_ids
