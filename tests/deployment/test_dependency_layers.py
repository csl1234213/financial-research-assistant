"""Contracts for runtime, development, UI, and training dependency isolation."""

from __future__ import annotations

import os
import re
from pathlib import Path

import config
import config.ui

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9_.-]+)")


def _requirement_closure(path: Path) -> list[str]:
    entries: list[str] = []
    visited: set[Path] = set()

    def visit(current: Path) -> None:
        current = current.resolve()
        if current in visited:
            return
        visited.add(current)

        for raw_line in current.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r "):
                visit(current.parent / line.removeprefix("-r ").strip())
                continue
            if line.startswith("--requirement "):
                visit(current.parent / line.removeprefix("--requirement ").strip())
                continue
            entries.append(line)

    visit(path)
    return entries


def _package_names(entries: list[str]) -> set[str]:
    names: set[str] = set()
    for entry in entries:
        match = REQUIREMENT_NAME.match(entry)
        if match and not entry.startswith("-"):
            names.add(match.group(1).lower().replace("_", "-"))
    return names


class TestDependencyLayering:
    def test_root_requirements_is_only_the_development_alias(self):
        lines = [
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

        assert lines == ["-r requirements/dev.txt"]

    def test_api_layer_keeps_the_full_inference_and_service_runtime(self):
        packages = _package_names(_requirement_closure(ROOT / "requirements" / "api.txt"))

        assert {
            "alembic",
            "anthropic",
            "chromadb",
            "fastapi",
            "langgraph",
            "openai",
            "psycopg",
            "psycopg2-binary",
            "redis",
            "sentence-transformers",
            "sqlalchemy",
            "torch",
            "transformers",
            "uvicorn",
        } <= packages

    def test_api_layer_excludes_development_ui_and_training_packages(self):
        packages = _package_names(_requirement_closure(ROOT / "requirements" / "api.txt"))

        assert packages.isdisjoint(
            {
                "accelerate",
                "bitsandbytes",
                "datasets",
                "peft",
                "pytest",
                "pytest-cov",
                "ruff",
                "streamlit",
                "trl",
            }
        )

    def test_development_ui_and_training_layers_remain_available(self):
        dev_packages = _package_names(_requirement_closure(ROOT / "requirements" / "dev.txt"))
        ui_packages = _package_names(_requirement_closure(ROOT / "requirements" / "ui.txt"))
        training_packages = _package_names(
            _requirement_closure(ROOT / "requirements" / "training.txt")
        )

        assert {"pytest", "pytest-cov", "ruff"} <= dev_packages
        assert "streamlit" in ui_packages
        assert {"accelerate", "datasets", "peft", "trl"} <= training_packages
        assert "streamlit" not in dev_packages
        assert training_packages.isdisjoint(dev_packages)

    def test_linux_and_windows_use_the_official_cpu_pytorch_wheel(self):
        base = (ROOT / "requirements" / "base.txt").read_text(encoding="utf-8")

        assert "--extra-index-url https://download.pytorch.org/whl/cpu" in base
        assert 'torch==2.12.1+cpu; sys_platform != "darwin"' in base
        assert 'torch==2.12.1; sys_platform == "darwin"' in base


class TestDependencyConsumers:
    def test_api_dockerfiles_install_only_the_api_layer(self):
        for relative_path in ("docker/Dockerfile.api", "Dockerfile"):
            content = (ROOT / relative_path).read_text(encoding="utf-8")

            assert "COPY requirements ./requirements" in content
            assert "pip install --no-cache-dir -r requirements/api.txt" in content
            assert "pip install --no-cache-dir -r requirements.txt" not in content
            assert "pip check" in content

    def test_ci_installs_the_explicit_development_layer(self):
        for relative_path in (
            ".github/workflows/ci.yml",
            ".github/workflows/production.yml",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")

            assert "pip install -r requirements/dev.txt" in content
            assert "pip install -r requirements.txt" not in content


def test_root_config_keeps_canonical_exports_when_ui_names_overlap():
    expected_upload_dir = Path(
        os.environ.get("UPLOAD_DIR", config.ROOT_DIR / "storage" / "uploads")
    )

    assert isinstance(config.UPLOAD_DIR, Path)
    assert config.UPLOAD_DIR == expected_upload_dir
    assert isinstance(config.ui.UPLOAD_DIR, str)

    # UI-only compatibility exports remain available from the package root.
    assert config.API_BASE_URL == config.ui.API_BASE_URL
    assert config.PAGE_TITLE == config.ui.PAGE_TITLE
