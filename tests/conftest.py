import gc
import os
import sys
import traceback
from pathlib import Path

import pytest

from PySide6.QtCore import QEvent, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from hexrdgui.main_window import MainWindow
from hexrdgui.messages_widget import MessagesWidget


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


@pytest.fixture(autouse=True)
def message_boxes(monkeypatch):
    """Record modal message boxes instead of letting them hang the run.

    Under `offscreen` nobody clicks "OK", so these block forever and the job
    goes quiet with no failing test to point at. Any box still recorded at
    teardown fails the test; a test that expects one checks it and clears it.
    """
    shown: list[str] = []

    def make_stub(method, result):
        def stub(parent, title, text='', *args, **kwargs):
            # The stack says which error path popped the box, which is what a
            # job that just went quiet cannot tell you.
            shown.append(
                f'QMessageBox.{method}({title!r}, {text!r})\n'
                + ''.join(traceback.format_stack()[:-1])
            )
            return result

        return stub

    # The helpers that spin their own modal event loop, and what each should
    # return in place of the button nobody is there to click.
    results = {
        'about': None,
        'critical': QMessageBox.StandardButton.Ok,
        'information': QMessageBox.StandardButton.Ok,
        'question': QMessageBox.StandardButton.No,
        'warning': QMessageBox.StandardButton.Ok,
    }
    for method, result in results.items():
        monkeypatch.setattr(QMessageBox, method, make_stub(method, result))

    yield shown

    assert not shown, 'Unexpected modal message box(es):\n' + '\n'.join(shown)


@pytest.fixture
def main_window(qtbot):
    # Clear the QSettings so we have a fresh run every time
    QSettings().clear()

    window = MainWindow()
    window.confirm_application_close = False
    qtbot.addWidget(window.ui)
    yield window

    # Release all messages widget Writers from stdout/stderr call stacks
    # before Qt destroys the underlying C++ objects. Various components
    # (e.g. indexing Runner, ImageLoadManager) may have created their own
    # ProgressDialogs with MessagesWidgets that also capture output, so
    # we drain the entire stack rather than releasing individual widgets.
    MessagesWidget.STDOUT_CALL_STACK[:] = [sys.__stdout__]
    MessagesWidget.STDERR_CALL_STACK[:] = [sys.__stderr__]
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__

    # Destroy the MainWindow QObject so Qt auto-disconnects all signal
    # connections (e.g. HexrdConfig signals → this window's slots), and so
    # dialogs created during the test fire their `destroyed` signal and
    # disconnect from the HexrdConfig singleton.
    #
    # NOTE: processEvents() alone does NOT process DeferredDelete events, so
    # deleteLater() would not actually destroy anything here -- the window and
    # its dialogs would linger (and stay connected to HexrdConfig) until some
    # later event-loop spin, leaking into subsequent tests. Force the deferred
    # deletions so destruction happens now, deterministically, on every
    # platform.
    window.deleteLater()
    QApplication.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


# This next fixture is necessary starting in Qt 6.8, to ensure
# all Qt objects are destroyed before Python finalizes.
# This may not be required anymore after we drop support
# for Python 3.11. The Python3.14 tests pass without it. We
# can try removing this after we drop support of Python versions.
@pytest.fixture(scope='session', autouse=True)
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
