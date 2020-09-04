from PySide2.QtCore import QEvent, QObject, Qt
from PySide2.QtWidgets import QDialog


class EnterKeyFilter(QObject):
    """An event filter to ignore <Enter> keys in QDialog instances.

    QButtonBox will **always** assign a default button to the <Enter> key,
    even if each button has its default and autoDefault properties explicitly
    set False. So to prevent a QDialog with QButtonBox from responding
    to the <Enter> key, install this filter on the QDialog instance.

    Note that this filter **only** filters QDialog objects.
    """
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and \
                event.key() == Qt.Key_Return and \
                isinstance(obj, QDialog):
            return True
        # (else) standard event processing
        return QObject.eventFilter(self, obj, event)


enter_key_filter = EnterKeyFilter()
