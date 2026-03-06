"""Additional edge-case tests for SortedTreeview."""

import tkinter as tk

import pytest

from app.ui.widgets.sorted_treeview import SortedTreeview


@pytest.fixture
def tree(shared_tk_root):
    if shared_tk_root is None:
        pytest.skip("Tkinter not available")
    widget = SortedTreeview(shared_tk_root, columns=("Name", "Value"), show="headings")
    yield widget
    try:
        widget.destroy()
    except tk.TclError:
        pass


def test_sort_column_handles_tclerror_for_one_row(tree, monkeypatch) -> None:
    i1 = tree.insert("", "end", values=("A", "20"))
    i2 = tree.insert("", "end", values=("B", "10"))
    original_set = tree.set

    def flaky_set(item, col=None, value=None):
        if item == i2 and value is None:
            raise tk.TclError("bad item")
        return original_set(item, col, value)

    monkeypatch.setattr(tree, "set", flaky_set)

    # Should not raise despite one row failing lookup
    tree.sort_column("Value", reverse=False)

    remaining_order = [tree.item(item, "values")[0] for item in tree.get_children("")]
    assert remaining_order[0] == "A"


def test_sort_column_falls_back_to_case_insensitive_string_sort(tree) -> None:
    tree.insert("", "end", values=("row1", "Bravo"))
    tree.insert("", "end", values=("row2", "alpha"))
    tree.insert("", "end", values=("row3", "charlie"))

    tree.sort_column("Value", reverse=False)
    ordered = [tree.item(item, "values")[1] for item in tree.get_children("")]
    assert ordered == ["alpha", "Bravo", "charlie"]


def test_sort_column_descending_places_dash_and_empty_first(tree) -> None:
    tree.insert("", "end", values=("row1", "15"))
    tree.insert("", "end", values=("row2", "-"))
    tree.insert("", "end", values=("row3", ""))

    tree.sort_column("Value", reverse=True)
    ordered = [tree.item(item, "values")[1] for item in tree.get_children("")]

    assert ordered[0] in {"-", ""}
    assert ordered[1] in {"-", ""}
    assert ordered[2] == "15"


def test_is_already_sorted_returns_false_when_set_raises(tree, monkeypatch) -> None:
    tree.insert("", "end", values=("row1", "10"))
    tree.insert("", "end", values=("row2", "20"))
    tree.set_default_sort("Value", reverse=False)

    monkeypatch.setattr(tree, "set", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert tree._is_already_sorted() is False
