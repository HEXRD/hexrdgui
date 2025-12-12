import gc
import os
from pathlib import Path

import pytest

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from hexrdgui.main_window import MainWindow


@pytest.fixture
def example_repo_path():
    if 'HEXRD_EXAMPLE_REPO_PATH' not in os.environ:
        pytest.fail('Environment varable HEXRD_EXAMPLE_REPO_PATH not set!')

    repo_path = os.environ['HEXRD_EXAMPLE_REPO_PATH']
    return Path(repo_path)


@pytest.fixture
def single_ge_path(example_repo_path):
    return example_repo_path / 'NIST_ruby/single_GE'


@pytest.fixture
def default_config_path(single_ge_path):
    return single_ge_path / 'include/ge_detector.yml'


@pytest.fixture
def default_data_path(single_ge_path):
    return single_ge_path / 'imageseries/RUBY_0000-fc_GE.npz'


@pytest.fixture
def main_window(qtbot):
    # Clear the QSettings so we have a fresh run every time
    QSettings().clear()

    window = MainWindow()
    window.confirm_application_close = False
    qtbot.addWidget(window.ui)
    return window


# This next fixture is necessary starting in Qt 6.8, to ensure
# all Qt objects are destroyed before Python finalizes.
# This may not be required anymore after we drop support
# for Python 3.11. The Python3.14 tests pass without it. We
# can try removing this after we drop support of Python versions.
@pytest.fixture(scope="session", autouse=True)
def cleanup_qt():
    """Clean up Qt objects before Python finalizes."""
    yield
    # After all tests complete, before Python exits
    app = QApplication.instance()
    if app:
        # Close all windows
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        # Process pending events
        app.processEvents()
    # Force garbage collection
    gc.collect()
