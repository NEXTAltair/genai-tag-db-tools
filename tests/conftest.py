"""pytest configuration for genai-tag-db-tools tests"""

import os


def pytest_configure(config):
    """Configure pytest markers and environment"""
    config.addinivalue_line("markers", "db_tools: genai-tag-db-tools specific tests")

    # Enable headless mode for GUI tests in CI/container environments
    if "DISPLAY" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
