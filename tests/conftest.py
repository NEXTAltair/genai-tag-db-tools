"""pytest configuration for genai-tag-db-tools tests"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Generator

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest markers and environment"""
    config.addinivalue_line("markers", "db_tools: genai-tag-db-tools specific tests")
    config.addinivalue_line(
        "markers",
        "requires_real_db: Tests requiring real database download (skipped in CI, run locally)"
    )

    # Enable headless mode for GUI tests in CI/container environments
    if "DISPLAY" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(autouse=True, scope="function")
def reset_runtime_for_real_db(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[None, None, None]:
    """Reset runtime state for real DB tests (CI: skip, Local: run with DB download)."""
    from genai_tag_db_tools.db import runtime

    # Check for requires_real_db marker
    markers = [m.name for m in request.node.iter_markers()]
    requires_real_db = "requires_real_db" in markers

    # CI environment check
    is_ci = os.environ.get("CI") == "true"

    if not requires_real_db:
        # Unit tests: skip DB initialization to detect uninitialized errors
        yield
        return

    if is_ci:
        # CI: Skip real DB tests (use Mock instead)
        pytest.skip("Skipping real DB test in CI environment")
        return

    # Local: Initialize real DB for integration tests
    user_db_dir = tmp_path / "user_db"
    user_db_dir.mkdir()
    runtime.init_user_db(user_db_dir)

    yield

    # Use public API for proper cleanup (ensures engine.dispose())
    runtime.close_all()
