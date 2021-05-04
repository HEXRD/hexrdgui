from contextlib import contextmanager
import sys

from PySide2.QtCore import QObject, Qt, Signal
from PySide2.QtGui import QColor

from hexrd.ui.ui_loader import UiLoader


STDOUT_COLOR = 'green'
STDERR_COLOR = 'red'


class MessagesWidget(QObject):

    # Signal args are the type ("stdout" or "stderr") and the message
    message_written = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('messages_widget.ui', parent)

        self.stdout_writer = Writer(self.write_stdout, self.ui)
        self.stderr_writer = Writer(self.write_stderr, self.ui)

        # Hold trailing returns to remove extra white space from the
        # bottom of the QTextEdit.
        self._holding_return = False

        self.setup_connections()

    def __del__(self):
        self.release_output()

    def setup_connections(self):
        self.ui.clear.pressed.connect(self.clear_text)
        self.ui.destroyed.connect(self.release_output)

    def capture_output(self):
        self.prev_stdout = sys.stdout
        self.prev_stderr = sys.stderr

        sys.stdout = self.stdout_writer
        sys.stderr = self.stderr_writer

    def release_output(self):
        if self.prev_stdout is not None:
            sys.stdout = self.prev_stdout
            self.prev_stdout = None

        if self.prev_stderr is not None:
            sys.stderr = self.prev_stderr
            self.prev_stderr = None

    def insert_text(self, text):
        # Remove trailing returns so there isn't extra white
        # space that always exists at the bottom of the text edit.
        if self._holding_return:
            text = '\n' + text
            self._holding_return = False

        if text.endswith('\n'):
            text = text[:-1]
            self._holding_return = True

        # Autoscroll if the scrollbar is at the end. Otherwise, do not.
        scrollbar = self.ui.text.verticalScrollBar()
        current = scrollbar.value()
        autoscroll = current == scrollbar.maximum()

        self.ui.text.insertPlainText(text)

        # Autoscroll
        scrollbar.setValue(scrollbar.maximum() if autoscroll else current)

    def write_stdout(self, text):
        with self.with_color(STDOUT_COLOR):
            self.insert_text(text)

        self.message_written.emit('stdout', text)

    def write_stderr(self, text):
        with self.with_color(STDERR_COLOR):
            self.insert_text(text)

        self.message_written.emit('stderr', text)

    @property
    def allow_clear(self):
        return self.ui.clear.isVisible()

    @allow_clear.setter
    def allow_clear(self, b):
        self.ui.clear.setVisible(b)

    def clear_text(self):
        self.ui.text.clear()

    @contextmanager
    def with_color(self, color):
        text_edit = self.ui.text
        prev_qcolor = text_edit.textColor()
        text_edit.setTextColor(QColor(color))
        try:
            yield
        finally:
            text_edit.setTextColor(prev_qcolor)

    @property
    def prev_stdout(self):
        return self.stdout_writer.prev_writer

    @prev_stdout.setter
    def prev_stdout(self, v):
        self.stdout_writer.prev_writer = v

    @property
    def prev_stderr(self):
        return self.stderr_writer.prev_writer

    @prev_stderr.setter
    def prev_stderr(self, v):
        self.stderr_writer.prev_writer = v


class Writer(QObject):

    text_received = Signal(str)

    def __init__(self, write_func, parent=None):
        super().__init__(parent)
        self.write_func = write_func

        # Always write to the previous writer first
        self.prev_writer = None

        self.setup_connections()

    def setup_connections(self):
        # Always do a queued connection so the messages are
        # printed in the order they are received (regardless of which
        # thread they are coming from)
        self.text_received.connect(self.on_text_received, Qt.QueuedConnection)

    def on_text_received(self, text):
        self.write_func(text)

    def write(self, text):
        if self.prev_writer is not None:
            # First, write to the previous writer.
            # This is so that messages will always get to the original stdout
            # and stderr, even if events do not get processed in the Qt event
            # loop, which can happen if an exception or seg fault occurs.
            self.prev_writer.write(text)

        self.text_received.emit(text)
