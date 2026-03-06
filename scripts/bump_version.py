"""Bump project version across pyproject and PyInstaller spec files.

Usage examples:
    python scripts/bump_version.py --patch
    python scripts/bump_version.py --minor --dry-run
"""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path
from typing import Callable

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse MAJOR.MINOR.PATCH into a tuple."""
    match = SEMVER_RE.fullmatch(version)
    if not match:
        raise ValueError(f"Invalid semantic version: {version!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def bump_semver(version: str, bump_type: str) -> str:
    """Return incremented version for a selected bump type."""
    major, minor, patch = parse_semver(version)
    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        raise ValueError(f"Unsupported bump type: {bump_type!r}")
    return f"{major}.{minor}.{patch}"


def to_windows_file_version(version: str) -> str:
    """Convert MAJOR.MINOR.PATCH to MAJOR.MINOR.PATCH.0 format."""
    major, minor, patch = parse_semver(version)
    return f"{major}.{minor}.{patch}.0"


def to_windows_file_tuple(version: str) -> str:
    """Convert MAJOR.MINOR.PATCH to '(MAJOR, MINOR, PATCH, 0)' text."""
    major, minor, patch = parse_semver(version)
    return f"({major}, {minor}, {patch}, 0)"


def replace_exactly_once(
    text: str,
    pattern: str,
    replacement: str | Callable[[re.Match[str]], str],
    field_name: str,
    file_path: Path,
) -> str:
    """Replace a pattern exactly once, or fail fast."""
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one '{field_name}' occurrence in {file_path}, found {count}."
        )
    return updated


def update_pyproject_version(pyproject_path: Path, new_version: str) -> None:
    """Update [project].version in pyproject.toml."""
    text = pyproject_path.read_text(encoding="utf-8")
    updated = replace_exactly_once(
        text=text,
        pattern=r'(^\[project\]\s*$.*?^version\s*=\s*")(\d+\.\d+\.\d+)(")',
        replacement=rf"\g<1>{new_version}\g<3>",
        field_name="project.version",
        file_path=pyproject_path,
    )
    pyproject_path.write_text(updated, encoding="utf-8")


def update_app_init_version(init_path: Path, new_version: str) -> None:
    """Update __version__ in app/__init__.py."""
    text = init_path.read_text(encoding="utf-8")
    updated = replace_exactly_once(
        text=text,
        pattern=r'^(__version__\s*=\s*")(\d+\.\d+\.\d+)(")',
        replacement=rf"\g<1>{new_version}\g<3>",
        field_name="app.__version__",
        file_path=init_path,
    )
    init_path.write_text(updated, encoding="utf-8")


def update_spec_file(spec_path: Path, new_version: str) -> None:
    """Update all version fields in a PyInstaller spec file."""
    text = spec_path.read_text(encoding="utf-8")
    windows_version = to_windows_file_version(new_version)
    windows_tuple = to_windows_file_tuple(new_version)

    text = replace_exactly_once(
        text=text,
        pattern=r"filevers=\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)",
        replacement=f"filevers={windows_tuple}",
        field_name="filevers",
        file_path=spec_path,
    )
    text = replace_exactly_once(
        text=text,
        pattern=r"prodvers=\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)",
        replacement=f"prodvers={windows_tuple}",
        field_name="prodvers",
        file_path=spec_path,
    )
    text = replace_exactly_once(
        text=text,
        pattern=r"StringStruct\((['\"])FileVersion\1,\s*(['\"])\d+\.\d+\.\d+\.\d+\2\)",
        replacement=f"StringStruct('FileVersion', '{windows_version}')",
        field_name="FileVersion",
        file_path=spec_path,
    )
    text = replace_exactly_once(
        text=text,
        pattern=r"StringStruct\((['\"])ProductVersion\1,\s*(['\"])\d+\.\d+\.\d+\.\d+\2\)",
        replacement=f"StringStruct('ProductVersion', '{windows_version}')",
        field_name="ProductVersion",
        file_path=spec_path,
    )
    spec_path.write_text(text, encoding="utf-8")


def get_project_version(base_dir: Path) -> str:
    """Read current version from pyproject.toml [project].version."""
    pyproject_path = base_dir / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    project = data.get("project", {})
    version = project.get("version")
    if not isinstance(version, str):
        raise RuntimeError(f"Missing or invalid [project].version in {pyproject_path}")
    parse_semver(version)
    return version


def update_versions(base_dir: Path, new_version: str, dry_run: bool = False) -> list[Path]:
    """Update all versioned files for a release."""
    parse_semver(new_version)

    pyproject_path = base_dir / "pyproject.toml"
    app_init_path = base_dir / "app" / "__init__.py"
    onefile_spec = base_dir / "WoosNwnParser-onefile.spec"
    onedir_spec = base_dir / "WoosNwnParser-onedir.spec"

    paths = [pyproject_path, app_init_path, onefile_spec, onedir_spec]
    missing = [path for path in paths if not path.exists()]
    if missing:
        missing_joined = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Expected file(s) not found: {missing_joined}")

    if dry_run:
        return paths

    update_pyproject_version(pyproject_path, new_version)
    update_app_init_version(app_init_path, new_version)
    update_spec_file(onefile_spec, new_version)
    update_spec_file(onedir_spec, new_version)
    return paths


def build_arg_parser() -> argparse.ArgumentParser:
    """Create CLI parser."""
    parser = argparse.ArgumentParser(description="Bump version across release files.")
    bump_group = parser.add_mutually_exclusive_group(required=True)
    bump_group.add_argument("--major", action="store_true", help="Bump major version.")
    bump_group.add_argument("--minor", action="store_true", help="Bump minor version.")
    bump_group.add_argument("--patch", action="store_true", help="Bump patch version.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview target version and files without writing.",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("."),
        help="Repository root containing pyproject.toml (default: current directory).",
    )
    return parser


def main() -> int:
    """CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.major:
        bump_type = "major"
    elif args.minor:
        bump_type = "minor"
    else:
        bump_type = "patch"

    base_dir = args.base_dir.resolve()
    current_version = get_project_version(base_dir)
    new_version = bump_semver(current_version, bump_type)

    updated_paths = update_versions(base_dir=base_dir, new_version=new_version, dry_run=args.dry_run)

    action = "Would update" if args.dry_run else "Updated"
    print(f"{action} version: {current_version} -> {new_version}")
    for path in updated_paths:
        try:
            relative = path.relative_to(base_dir)
            print(f"- {relative}")
        except ValueError:
            print(f"- {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
