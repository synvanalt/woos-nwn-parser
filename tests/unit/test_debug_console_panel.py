"""Unit tests for DebugConsolePanel behavior."""

import tkinter as tk
from tkinter import ttk
from unittest.mock import Mock

import pytest

import app.ui.widgets.debug_console_panel as debug_console_module
from app.ui.widgets.debug_console_panel import DebugConsolePanel


@pytest.fixture
def debug_panel(shared_tk_root):
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")
    notebook = ttk.Notebook(shared_tk_root)
    panel = DebugConsolePanel(notebook)
    return panel


def test_log_does_not_insert_when_debug_disabled(debug_panel) -> None:
    debug_panel.debug_mode_var.set(False)
    debug_panel.text.insert = Mock()
    debug_panel.text.see = Mock()

    debug_panel.log("hello", "info")

    debug_panel.text.insert.assert_not_called()
    debug_panel.text.see.assert_not_called()


def test_log_inserts_and_autoscrolls_when_at_bottom(debug_panel) -> None:
    debug_panel.debug_mode_var.set(True)
    debug_panel.text.yview = Mock(return_value=(0.0, 1.0))
    debug_panel.text.insert = Mock()
    debug_panel.text.see = Mock()

    debug_panel.log("hello", "warning")

    debug_panel.text.insert.assert_called_once()
    debug_panel.text.see.assert_called_once_with(tk.END)


def test_log_inserts_without_autoscroll_when_not_at_bottom(debug_panel) -> None:
    debug_panel.debug_mode_var.set(True)
    debug_panel.text.yview = Mock(return_value=(0.0, 0.7))
    debug_panel.text.insert = Mock()
    debug_panel.text.see = Mock()

    debug_panel.log("hello", "error")

    debug_panel.text.insert.assert_called_once()
    debug_panel.text.see.assert_not_called()


def test_clear_and_debug_enabled_helpers(debug_panel) -> None:
    debug_panel.text.delete = Mock()
    debug_panel.clear()
    debug_panel.text.delete.assert_called_once_with(1.0, tk.END)

    debug_panel.set_debug_enabled(True)
    assert debug_panel.get_debug_enabled() is True
    debug_panel.set_debug_enabled(False)
    assert debug_panel.get_debug_enabled() is False


def test_init_uses_fallback_font_when_theme_font_missing(shared_tk_root, monkeypatch) -> None:
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")

    notebook = ttk.Notebook(shared_tk_root)
    fallback_font = Mock()
    monkeypatch.setattr(
        debug_console_module.font,
        "nametofont",
        lambda _name: (_ for _ in ()).throw(tk.TclError("missing theme font")),
    )
    monkeypatch.setattr(debug_console_module.font, "Font", Mock(return_value=fallback_font))

    panel = DebugConsolePanel(notebook)
    assert panel.theme_font is fallback_font


def test_log_uses_debug_tag_by_default(debug_panel) -> None:
    debug_panel.debug_mode_var.set(True)
    debug_panel.text.yview = Mock(return_value=(0.0, 1.0))
    debug_panel.text.insert = Mock()

    debug_panel.log("hello")

    assert debug_panel.text.insert.call_count == 1
    assert debug_panel.text.insert.call_args.args[2] == "debug"
