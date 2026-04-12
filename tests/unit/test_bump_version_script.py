"""Tests for scripts/bump_version.py."""

from __future__ import annotations

import importlib.util
import shutil
import uuid
from datetime import date
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


def create_release_workspace(tmp_path: Path) -> None:
    """Create the minimal release-file layout needed by bump_version.py."""
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "docs" / "releases").mkdir(parents=True)
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
        '__version__ = "1.3.1"\n',
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

    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n"
        "- New release automation helper\n\n"
        "### Fixed\n"
        "- Dry-run now previews release docs too\n\n"
        "## [1.3.1] - 2026-03-01\n\n"
        "### Fixed\n"
        "- Previous shipped fix\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "releases" / "v1.3.1.md").write_text(
        "### Description\n\n"
        "Release template body.\n\n"
        "### Security Scan\n\n"
        "**One file approach** - VirusTotal: "
        "[2/72 vendors flagged](https://example.com/onefile)\n\n"
        "**One directory approach** - VirusTotal: "
        "[1/72 vendors flagged](https://example.com/onedir)\n\n"
        "### Changelog\n\n"
        "#### Changed\n"
        "- Old release notes\n",
        encoding="utf-8",
    )


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
        create_release_workspace(tmp_path)

        changed_paths = module.update_versions(tmp_path, "1.3.2", dry_run=False)
        assert len(changed_paths) == 6

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

        release_date = date.today().isoformat()
        changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
        assert changelog.startswith("# Changelog\n\n## [Unreleased]\n\n## [1.3.2] - ")
        assert f"## [1.3.2] - {release_date}" in changelog
        assert "### Added\n- New release automation helper" in changelog
        assert "### Fixed\n- Dry-run now previews release docs too" in changelog

        new_release = (tmp_path / "docs" / "releases" / "v1.3.2.md").read_text(encoding="utf-8")
        assert "#### Added\n- New release automation helper" in new_release
        assert "#### Fixed\n- Dry-run now previews release docs too" in new_release
        assert "\n### Added\n- New release automation helper" not in new_release
        assert "[X/72 vendors flagged](https://example.com/onefile)" in new_release
        assert "[X/72 vendors flagged](https://example.com/onedir)" in new_release
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_update_versions_dry_run_does_not_modify_files() -> None:
    module = load_bump_version_module()

    tmp_path = make_workspace_tmp_dir()
    try:
        create_release_workspace(tmp_path)

        before_pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        before_init = (tmp_path / "app" / "__init__.py").read_text(encoding="utf-8")
        before_changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
        before_release = (tmp_path / "docs" / "releases" / "v1.3.1.md").read_text(encoding="utf-8")

        changed_paths = module.update_versions(tmp_path, "1.3.2", dry_run=True)

        after_pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        after_init = (tmp_path / "app" / "__init__.py").read_text(encoding="utf-8")
        after_changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
        after_release = (tmp_path / "docs" / "releases" / "v1.3.1.md").read_text(encoding="utf-8")
        assert before_pyproject == after_pyproject
        assert before_init == after_init
        assert before_changelog == after_changelog
        assert before_release == after_release
        assert not (tmp_path / "docs" / "releases" / "v1.3.2.md").exists()
        assert len(changed_paths) == 6
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_update_versions_fails_when_unreleased_section_is_empty() -> None:
    module = load_bump_version_module()

    tmp_path = make_workspace_tmp_dir()
    try:
        create_release_workspace(tmp_path)
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Unreleased]\n\n## [1.3.1] - 2026-03-01\n",
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match="Section '\\[Unreleased\\]'"):
            module.update_versions(tmp_path, "1.3.2", dry_run=False)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_update_versions_fails_when_target_release_note_exists() -> None:
    module = load_bump_version_module()

    tmp_path = make_workspace_tmp_dir()
    try:
        create_release_workspace(tmp_path)
        (tmp_path / "docs" / "releases" / "v1.3.2.md").write_text(
            "already exists\n",
            encoding="utf-8",
        )

        with pytest.raises(FileExistsError, match="Target release note already exists"):
            module.update_versions(tmp_path, "1.3.2", dry_run=False)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_build_release_notes_requires_two_virustotal_badges() -> None:
    module = load_bump_version_module()

    bad_template = (
        "### Description\n\n"
        "Only one badge here.\n\n"
        "### Security Scan\n\n"
        "**One file approach** - VirusTotal: "
        "[2/72 vendors flagged](https://example.com/onefile)\n\n"
        "### Changelog\n\n"
        "#### Fixed\n"
        "- Old release notes\n"
    )

    with pytest.raises(RuntimeError, match="Expected exactly two VirusTotal badge lines"):
        module.build_release_notes(
            bad_template,
            released_changelog_body="### Fixed\n- New notes\n",
            release_path=Path("docs/releases/v1.3.2.md"),
        )


def test_build_release_notes_requires_changelog_section() -> None:
    module = load_bump_version_module()

    bad_template = (
        "### Description\n\n"
        "Missing changelog section.\n\n"
        "### Security Scan\n\n"
        "**One file approach** - VirusTotal: "
        "[2/72 vendors flagged](https://example.com/onefile)\n\n"
        "**One directory approach** - VirusTotal: "
        "[1/72 vendors flagged](https://example.com/onedir)\n"
    )

    with pytest.raises(RuntimeError, match="release changelog section"):
        module.build_release_notes(
            bad_template,
            released_changelog_body="### Fixed\n- New notes\n",
            release_path=Path("docs/releases/v1.3.2.md"),
        )
