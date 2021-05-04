from PySide2.QtCore import QBuffer, QByteArray
from PySide2.QtUiTools import QUiLoader
from PySide2.QtWidgets import QDialog

from hexrd.ui import enter_key_filter, resource_loader

from hexrd.ui.image_canvas import ImageCanvas
from hexrd.ui.image_tab_widget import ImageTabWidget
from hexrd.ui.scientificspinbox import ScientificDoubleSpinBox
from hexrd.ui.singletons import QSingleton

import hexrd.ui.resources.ui


class UiLoader(QUiLoader, metaclass=QSingleton):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.registerCustomWidget(ImageCanvas)
        self.registerCustomWidget(ImageTabWidget)
        self.registerCustomWidget(ScientificDoubleSpinBox)

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
        ui = self.load(buf, parent)

        # Perform any custom processing on the ui
        self.process_ui(ui)
        return ui

    def process_ui(self, ui):
        """Perform any additional processing on loaded UI objects

        Currently: it installs an enter key filter for QDialogs to prevent
        the enter key from closing them.
        """
        if isinstance(ui, QDialog):
            ui.installEventFilter(enter_key_filter)
