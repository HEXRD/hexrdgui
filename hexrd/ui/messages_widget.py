from contextlib import contextmanager
import sys

from PySide2.QtCore import QObject, Qt, Signal
from PySide2.QtGui import QColor

from hexrd.ui.fix_pdb import fix_pdb
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


STDOUT_COLOR = 'green'
STDERR_COLOR = 'red'


class MessagesWidget(QObject):

    # Signal args are the type ("stdout" or "stderr") and the message
    message_written = Signal(str, str)

    # Keep track of the call stacks so when one MessagesWidget is
    # deleted, it can properly assign sys.stdout and sys.stderr to
    # the next one in the stack.
    STDOUT_CALL_STACK = [sys.__stdout__]
    STDERR_CALL_STACK = [sys.__stderr__]

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('messages_widget.ui', parent)

        self.stdout_writer = Writer(self.write_stdout, self.ui)
        self.stderr_writer = Writer(self.write_stderr, self.ui)

        # Hold trailing returns to remove extra white space from the
        # bottom of the QTextEdit.
        self._holding_return = False

        self.capture_output()

        self.setup_connections()

    def __del__(self):
        self.release_output()

    def setup_connections(self):
        self.ui.clear.pressed.connect(self.clear_text)
        self.ui.destroyed.connect(self.release_output)

    def capture_output(self):
        # Get pdb to always use the default stdout and stderr
        fix_pdb()

        if self.stdout_writer not in self.STDOUT_CALL_STACK:
            self.stdout_writer.call_stack = self.STDOUT_CALL_STACK
            sys.stdout = self.stdout_writer
            self.STDOUT_CALL_STACK.append(self.stdout_writer)

        if self.stderr_writer not in self.STDERR_CALL_STACK:
            self.stderr_writer.call_stack = self.STDERR_CALL_STACK
            sys.stderr = self.stderr_writer
            self.STDERR_CALL_STACK.append(self.stderr_writer)

        self.update_logging_streams()

    def release_output(self):
        stack = self.STDOUT_CALL_STACK
        if self.stdout_writer in stack:
            i = stack.index(self.stdout_writer)
            sys.stdout = stack[i - 1]
            stack.pop(i)

        stack = self.STDERR_CALL_STACK
        if self.stderr_writer in stack:
            i = stack.index(self.stderr_writer)
            sys.stderr = stack[i - 1]
            stack.pop(i)

        self.update_logging_streams()

    def update_logging_streams(self):
        HexrdConfig().logging_stdout_stream = sys.stdout
        HexrdConfig().logging_stderr_stream = sys.stderr

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
        self._holding_return = False
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


class Writer(QObject):

    text_received = Signal(str)

    def __init__(self, write_func, parent=None):
        super().__init__(parent)
        self.write_func = write_func

        # Call the previous writer in the call stack first
        self.call_stack = []

        self.setup_connections()

    def setup_connections(self):
        # Always do a queued connection so the messages are
        # printed in the order they are received (regardless of which
        # thread they are coming from)
        self.text_received.connect(self.on_text_received, Qt.QueuedConnection)

    def on_text_received(self, text):
        self.write_func(text)

    def write(self, text):
        if self in self.call_stack:
            # First, write to the previous writer.
            # This is so that messages will always get to the original stdout
            # and stderr, even if events do not get processed in the Qt event
            # loop, which can happen if an exception or seg fault occurs.
            i = self.call_stack.index(self)
            self.call_stack[i - 1].write(text)

        self.text_received.emit(text)

    def flush(self):
        if self in self.call_stack:
            # Flush the previous writer.
            i = self.call_stack.index(self)
            self.call_stack[i - 1].flush()

        # We don't need to flush the Writer class...
