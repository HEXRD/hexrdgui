from PySide2.QtCore import QBuffer, QByteArray, QFile
from PySide2.QtUiTools import QUiLoader

from hexrd.ui import resource_loader

from .image_canvas import ImageCanvas
from .image_tab_widget import ImageTabWidget

import hexrd.ui.resources.ui

class UiLoader(QUiLoader):
    def __init__(self, parent=None):
        super(UiLoader, self).__init__(parent)

        self.registerCustomWidget(ImageCanvas)
        self.registerCustomWidget(ImageTabWidget)

    def load_file(self, file_name, parent=None):
        """Load a UI file and return the widget

        Returns a widget created from the UI file.

        :param file_name: The name of the ui file to load (must be located
                          in hexrd.resources.ui).
        """
        text = resource_loader.load_resource(hexrd.ui.resources.ui, file_name)
        return self.load_string(text, parent)

    def load_string(self, string, parent=None):
        """Load a UI file from a string and return the widget"""
        data = QByteArray(string.encode('utf-8'))
        buf = QBuffer(data)
        return self.load(buf, parent)
