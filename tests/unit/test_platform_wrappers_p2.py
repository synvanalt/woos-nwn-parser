"""P2 unit tests for entrypoint/platform wrapper helpers."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import tkinter as tk

import app.__main__ as entrypoint_module
import app.ui.window_style as window_style_module


def test_get_resource_path_uses_dev_base_when_meipass_missing(monkeypatch) -> None:
    monkeypatch.delattr(entrypoint_module.sys, "_MEIPASS", raising=False)

    result = entrypoint_module.get_resource_path("app/assets/icons/ir_fighter.ico")

    expected_base = Path(entrypoint_module.__file__).parent.parent
    assert result == expected_base / "app/assets/icons/ir_fighter.ico"


def test_get_resource_path_uses_meipass_when_available(monkeypatch) -> None:
    monkeypatch.setattr(entrypoint_module.sys, "_MEIPASS", "C:/bundle_root", raising=False)

    result = entrypoint_module.get_resource_path("x/y.txt")

    assert result == Path("C:/bundle_root") / "x/y.txt"


def test_apply_root_icon_falls_back_then_reapplies_on_success() -> None:
    root = Mock()
    root.iconbitmap.side_effect = [Exception("kw failed"), None, None]
    icon = Path("C:/icons/test.ico")

    entrypoint_module.apply_root_icon(root, icon)

    assert root.iconbitmap.call_count == 3
    assert root.iconbitmap.call_args_list[0].kwargs == {"default": str(icon)}
    assert root.iconbitmap.call_args_list[1].args == (str(icon),)
    assert root.iconbitmap.call_args_list[2].args == (str(icon),)


def test_apply_root_icon_returns_when_both_attempts_fail() -> None:
    root = Mock()
    root.iconbitmap.side_effect = [Exception("kw failed"), Exception("positional failed")]

    entrypoint_module.apply_root_icon(root, Path("C:/icons/test.ico"))

    assert root.iconbitmap.call_count == 2


def test_fix_treeview_indicator_noops_when_theme_images_unavailable() -> None:
    root = SimpleNamespace()
    root.tk = Mock()
    root.tk.eval.side_effect = tk.TclError("no theme image")

    entrypoint_module.fix_treeview_indicator(root)

    assert not hasattr(root, "_fix_treeview_indicator")
    assert not hasattr(root, "_sv_ttk_down_img")
    assert not hasattr(root, "_sv_ttk_right_img")


def test_fix_treeview_indicator_wires_bindings_and_initial_images() -> None:
    root = Mock()
    root.tk = Mock()

    def eval_side_effect(command: str):
        if "I(down)" in command:
            return "img-down"
        if "I(right)" in command:
            return "img-right"
        return ""

    root.tk.eval.side_effect = eval_side_effect

    entrypoint_module.fix_treeview_indicator(root)

    class FakeTree:
        def __init__(self) -> None:
            self._bindings = {}
            self._children = {"": ["parent", "leaf"], "parent": ["child"], "leaf": [], "child": []}
            self._open = {"parent": True}
            self._focus = "parent"
            self.updated_images = []

        def get_children(self, item: str = ""):
            return self._children.get(item, [])

        def item(self, item: str, option: str | None = None, **kwargs):
            if kwargs:
                if "open" in kwargs:
                    self._open[item] = kwargs["open"]
                if "image" in kwargs:
                    self.updated_images.append((item, kwargs["image"]))
                return None
            if option == "open":
                return self._open.get(item, False)
            return None

        def bind(self, event: str, callback, add=None) -> None:
            self._bindings[event] = callback

        def identify_region(self, _x: int, _y: int) -> str:
            return "tree"

        def identify_row(self, _y: int) -> str:
            return "parent"

        def focus(self) -> str:
            return self._focus

    tree = FakeTree()
    root._fix_treeview_indicator(tree)

    assert "<Button-1>" in tree._bindings
    assert "<<TreeviewOpen>>" in tree._bindings
    assert "<<TreeviewClose>>" in tree._bindings
    assert hasattr(tree, "_update_indicators")
    assert ("parent", "img-down") in tree.updated_images

    click_result = tree._bindings["<Button-1>"](SimpleNamespace(x=1, y=1))
    assert click_result == "break"
    assert tree._open["parent"] is False
    assert ("parent", "img-right") in tree.updated_images

    tree._bindings["<<TreeviewOpen>>"](SimpleNamespace())
    tree._bindings["<<TreeviewClose>>"](SimpleNamespace())
    assert tree.updated_images[-2:] == [("parent", "img-down"), ("parent", "img-right")]


def test_apply_dark_title_bar_returns_when_windll_missing(monkeypatch) -> None:
    monkeypatch.delattr(window_style_module.ctypes, "windll", raising=False)
    window = Mock()

    window_style_module.apply_dark_title_bar(window)

    window.after.assert_not_called()


def test_apply_dark_title_bar_retries_until_window_handle_is_ready(monkeypatch) -> None:
    calls = {"get_parent": 0, "set_attr": 0}

    def fake_get_parent(_winfo_id: int) -> int:
        calls["get_parent"] += 1
        return 0 if calls["get_parent"] < 3 else 101

    def fake_set_window_attribute(_hwnd, _attr, _value_ptr, _size) -> int:
        calls["set_attr"] += 1
        return 0

    fake_windll = SimpleNamespace(
        dwmapi=SimpleNamespace(DwmSetWindowAttribute=fake_set_window_attribute),
        user32=SimpleNamespace(GetParent=fake_get_parent),
    )
    monkeypatch.setattr(window_style_module.ctypes, "windll", fake_windll, raising=False)

    class FakeWindow:
        def __init__(self) -> None:
            self.after_calls = 0

        def winfo_id(self) -> int:
            return 555

        def after(self, _ms: int, callback) -> None:
            self.after_calls += 1
            callback()

    window = FakeWindow()
    window_style_module.apply_dark_title_bar(window)

    assert calls["get_parent"] == 3
    assert calls["set_attr"] == 1
    assert window.after_calls == 2
