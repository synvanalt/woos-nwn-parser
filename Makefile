APP_NAME := WoosNwnParser
PYTHON ?= python

ONEFILE_SPEC := WoosNwnParser-onefile.spec
ONEDIR_SPEC := WoosNwnParser-onedir.spec

.DEFAULT_GOAL := help

.PHONY: help run install install-dev test test-cov lint format type-check check \
	build build-onefile build-onedir clean clean-build clean-python benchmark \
	bump-patch bump-minor bump-major bump-dry-run

help:
	@echo "Woo's NWN Parser - Available Commands:"
	@echo "  make run            - Run the application"
	@echo "  make build          - Build onefile executable (default build target)"
	@echo "  make build-onefile  - Build single-file executable via PyInstaller spec"
	@echo "  make build-onedir   - Build one-directory executable via PyInstaller spec"
	@echo "  make clean          - Remove Python cache + build/test artifacts"
	@echo "  make clean-python   - Remove Python cache files only"
	@echo "  make clean-build    - Remove build/dist/obfuscated folders"
	@echo "  make install        - Install runtime dependencies"
	@echo "  make install-dev    - Install test + build dependencies"
	@echo "  make lint           - Run ruff checks"
	@echo "  make format         - Format code with ruff formatter"
	@echo "  make type-check     - Run mypy"
	@echo "  make test           - Run full test suite"
	@echo "  make test-cov       - Run tests with coverage reports"
	@echo "  make check          - Run lint + type-check + tests"
	@echo "  make benchmark      - Run baseline parser/import benchmark"
	@echo "  make bump-patch     - Bump patch version across release files"
	@echo "  make bump-minor     - Bump minor version across release files"
	@echo "  make bump-major     - Bump major version across release files"
	@echo "  make bump-dry-run   - Preview next patch bump without writing"

run:
	$(PYTHON) -m app

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -e ".[test,build]"

lint:
	$(PYTHON) -m ruff check app tests

format:
	$(PYTHON) -m ruff format app tests

type-check:
	$(PYTHON) -m mypy app

test:
	$(PYTHON) -m pytest tests/unit tests/integration tests/e2e -v

test-cov:
	$(PYTHON) -m pytest tests/unit tests/integration tests/e2e --cov=app --cov-report=term-missing --cov-report=html

check: lint type-check test

build: build-onefile

build-onefile:
	$(PYTHON) -m PyInstaller --clean $(ONEFILE_SPEC)

build-onedir:
	$(PYTHON) -m PyInstaller --clean $(ONEDIR_SPEC)

benchmark:
	$(PYTHON) scripts/benchmark_baseline.py

bump-patch:
	$(PYTHON) scripts/bump_version.py --patch

bump-minor:
	$(PYTHON) scripts/bump_version.py --minor

bump-major:
	$(PYTHON) scripts/bump_version.py --major

bump-dry-run:
	$(PYTHON) scripts/bump_version.py --patch --dry-run

clean: clean-python clean-build
	$(PYTHON) -c "from pathlib import Path; [p.unlink() for p in Path('.').glob('*.log') if p.is_file()]"

clean-python:
	$(PYTHON) -c "from pathlib import Path; import shutil; [p.unlink() for p in Path('.').rglob('*.pyc') if p.is_file()]; [p.unlink() for p in Path('.').rglob('*.pyo') if p.is_file()]; [shutil.rmtree(p, ignore_errors=True) for p in Path('.').rglob('__pycache__') if p.is_dir()]"

clean-build:
	$(PYTHON) -c "from pathlib import Path; import shutil; targets=['.pytest_cache','htmlcov','.coverage','build','dist','obfuscated']; [shutil.rmtree(Path(t), ignore_errors=True) if Path(t).is_dir() else (Path(t).unlink() if Path(t).exists() else None) for t in targets]"

