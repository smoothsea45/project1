import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name != "nt":
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/pharma-cost-test-cache")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
