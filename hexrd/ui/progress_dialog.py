from PySide2.QtCore import QEvent, QObject, QTimer, Qt

from hexrd.ui.messages_widget import MessagesWidget
from hexrd.ui.ui_loader import UiLoader


class ProgressDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('progress_dialog.ui', parent)

        self.messages_widget = MessagesWidget(self.ui)
        # Disable message widget buttons
        self.messages_widget.allow_copy = False
        self.messages_widget.allow_clear = False
        self.ui.messages_widget_layout.addWidget(self.messages_widget.ui)

        # Some default window title and text
        self.setWindowTitle('Hexrd')
        self.setLabelText('Please wait...')

        self.block_escape_key_filter = BlockEscapeKeyFilter(self.ui)
        self.ui.installEventFilter(self.block_escape_key_filter)

        # No close button in the corner
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags((flags | Qt.CustomizeWindowHint) &
                               ~Qt.WindowCloseButtonHint)

        self.setup_connections()

    def setup_connections(self):
        # Show the messages widget if a message is received
        self.messages_widget.message_written.connect(self.show_messages_widget)

    def show_messages_widget(self):
        self.messages_widget.ui.show()

    def clear_messages(self):
        self.messages_widget.clear_text()

    def shrink_later(self):
        QTimer.singleShot(0, lambda: self.ui.adjustSize())

    # We are copying some of the functions of QProgressDialog to ease
    # the transition to this...
    def setWindowTitle(self, title):
        self.ui.setWindowTitle(title)

    def setLabelText(self, text):
        self.ui.progress_label.setText(text)

    def setRange(self, minimum, maximum):
        self.ui.progress_bar.setRange(minimum, maximum)

    def value(self):
        return self.ui.progress_bar.value()

    def setValue(self, value):
        self.ui.progress_bar.setValue(value)

    def accept(self):
        self.ui.accept()

    def reset_messages(self):
        self.clear_messages()
        # Hide the messages widget until a message is received
        self.messages_widget.ui.hide()

        # Shrink the dialog to the size of the contents
        self.shrink_later()

    def exec_(self):
        self.reset_messages()
        self.ui.exec_()

    def exec_later(self):
        QTimer.singleShot(0, lambda: self.exec_())


class BlockEscapeKeyFilter(QObject):
    # Prevent the user from closing the dialog with the escape key
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            return True
        return super().eventFilter(obj, event)
