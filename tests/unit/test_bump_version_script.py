"""Tests for scripts/bump_version.py."""

from __future__ import annotations

import importlib.util
import shutil
import uuid
from pathlib import Path
from types import ModuleType

import pytest


def load_bump_version_module() -> ModuleType:
    """Load scripts/bump_version.py as a module for unit testing."""
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_workspace_tmp_dir() -> Path:
    """Create a writable temp directory under tests-round-time."""
    repo_root = Path(__file__).resolve().parents[2]
    parent = repo_root / "tests-round-time"
    parent.mkdir(parents=True, exist_ok=True)
    temp_dir = parent / f"bump-version-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    return temp_dir


def test_bump_semver_patch() -> None:
    module = load_bump_version_module()
    assert module.bump_semver("1.3.1", "patch") == "1.3.2"


def test_bump_semver_minor() -> None:
    module = load_bump_version_module()
    assert module.bump_semver("1.3.1", "minor") == "1.4.0"


def test_bump_semver_major() -> None:
    module = load_bump_version_module()
    assert module.bump_semver("1.3.1", "major") == "2.0.0"


def test_parse_semver_rejects_invalid_value() -> None:
    module = load_bump_version_module()
    with pytest.raises(ValueError):
        module.parse_semver("1.3")


def test_update_versions_updates_all_targets() -> None:
    module = load_bump_version_module()

    tmp_path = make_workspace_tmp_dir()
    try:
        (tmp_path / "app").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text(
            """
[project]
name = "woos-nwn-parser"
version = "1.3.1"
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (tmp_path / "app" / "__init__.py").write_text(
            '__version__ = "1.0.0"\n',
            encoding="utf-8",
        )

        spec_text = """
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(1, 3, 1, 0),
        prodvers=(1, 3, 1, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    '040904B0',
                    [
                        StringStruct('FileVersion', '1.3.1.0'),
                        StringStruct('ProductVersion', '1.3.1.0')
                    ]
                )
            ]
        ),
    ]
)
""".strip() + "\n"
        (tmp_path / "WoosNwnParser-onefile.spec").write_text(spec_text, encoding="utf-8")
        (tmp_path / "WoosNwnParser-onedir.spec").write_text(spec_text, encoding="utf-8")

        changed_paths = module.update_versions(tmp_path, "1.3.2", dry_run=False)
        assert len(changed_paths) == 4

        pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        assert 'version = "1.3.2"' in pyproject

        init_text = (tmp_path / "app" / "__init__.py").read_text(encoding="utf-8")
        assert '__version__ = "1.3.2"' in init_text

        onefile = (tmp_path / "WoosNwnParser-onefile.spec").read_text(encoding="utf-8")
        onedir = (tmp_path / "WoosNwnParser-onedir.spec").read_text(encoding="utf-8")
        for text in (onefile, onedir):
            assert "filevers=(1, 3, 2, 0)" in text
            assert "prodvers=(1, 3, 2, 0)" in text
            assert "StringStruct('FileVersion', '1.3.2.0')" in text
            assert "StringStruct('ProductVersion', '1.3.2.0')" in text
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_update_versions_dry_run_does_not_modify_files() -> None:
    module = load_bump_version_module()

    tmp_path = make_workspace_tmp_dir()
    try:
        (tmp_path / "app").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nversion = "1.3.1"\n',
            encoding="utf-8",
        )
        (tmp_path / "app" / "__init__.py").write_text(
            '__version__ = "1.0.0"\n',
            encoding="utf-8",
        )
        minimal_spec = (
            "filevers=(1, 3, 1, 0)\n"
            "prodvers=(1, 3, 1, 0)\n"
            "StringStruct('FileVersion', '1.3.1.0')\n"
            "StringStruct('ProductVersion', '1.3.1.0')\n"
        )
        (tmp_path / "WoosNwnParser-onefile.spec").write_text(minimal_spec, encoding="utf-8")
        (tmp_path / "WoosNwnParser-onedir.spec").write_text(minimal_spec, encoding="utf-8")

        before_pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        before_init = (tmp_path / "app" / "__init__.py").read_text(encoding="utf-8")

        module.update_versions(tmp_path, "1.3.2", dry_run=True)

        after_pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        after_init = (tmp_path / "app" / "__init__.py").read_text(encoding="utf-8")
        assert before_pyproject == after_pyproject
        assert before_init == after_init
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
