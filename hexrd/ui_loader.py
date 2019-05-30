from PySide2.QtCore import QBuffer, QByteArray, QFile
from PySide2.QtUiTools import QUiLoader

from .image_viewer import ImageViewer
from .menu_bar import MenuBar
from .main_window import MainWindow
from .status_bar import StatusBar

import hexrd.resources.ui

try:
    import importlib.resources as importlib_resources
except ImportError:
    # Try backported to PY<37 `importlib_resources`.
    import importlib_resources

class UiLoader(QUiLoader):
    def __init__(self, parent=None):
        super(UiLoader, self).__init__(parent)

        self.registerCustomWidget(ImageViewer)
        self.registerCustomWidget(MainWindow)
        self.registerCustomWidget(MenuBar)
        self.registerCustomWidget(StatusBar)

    def load_file(self, file_name):
        """Load a UI file and return the widget

        Returns a widget created from the UI file.

        :param file_name: The name of the ui file to load (must be located
                          in hexrd.resources.ui).
        """
        text = importlib_resources.read_text(hexrd.resources.ui, file_name)
        return self.load_string(text)

    def load_string(self, string):
        """Load a UI file from a string and return the widget"""
        data = QByteArray(string.encode('utf-8'))
        buf = QBuffer(data)
        return self.load(buf)
