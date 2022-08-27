from PySide2.QtCore import QTimer
from PySide2.QtWidgets import QTabWidget


class HiddenBarTabWidget(QTabWidget):
    """This tab widget has a hidden tab bar

    It also resizes to match the size of the current tab.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_current_index_later(0)
        self.tabBar().hide()

    def set_current_index_later(self, index):
        QTimer.singleShot(0, lambda: self.setCurrentIndex(index))

    def sizeHint(self):
        size = self.currentWidget().sizeHint()
        size.setHeight(size.height() + 10)
        return size

    def minimumSizeHint(self):
        size = self.currentWidget().minimumSizeHint()
        size.setHeight(size.height() + 10)
        return size
