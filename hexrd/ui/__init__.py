from PySide2.QtCore import QEvent, QObject, Qt
from PySide2.QtWidgets import QDialog, QPushButton


class EnterKeyFilter(QObject):
    """An event filter to ignore <Enter> keys in QDialog instances.

    QDialogButtonBox will **always** assign a default button to the <Enter>
    key, even if each button has its default and autoDefault properties
    explicitly set False. So to prevent a QDialog with QDialogButtonBox from
    responding to the <Enter> key, install this filter on the QDialog instance.

    We must install the event filter on both the QDialog and on QPushButton
    children of QDialogButtonBoxes, because sometimes the QPushButton will
    receive the key press event, and sometimes the QDialog will receive it.
    When QDialog receives the key press event, it "clicks" the QPushButton,
    rather than forwarding the event to the QPushButton.

    Note that this filter **only** filters QDialog and QPushButton objects.
    """
    def eventFilter(self, obj, event):
        block = (
            event.type() == QEvent.KeyPress and
            event.key() in (Qt.Key_Return, Qt.Key_Enter) and
            isinstance(obj, (QDialog, QPushButton))
        )

        if block:
            return True

        return super().eventFilter(obj, event)


enter_key_filter = EnterKeyFilter()
