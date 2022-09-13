from PySide2.QtCore import QBuffer, QByteArray
from PySide2.QtUiTools import QUiLoader
from PySide2.QtWidgets import QDialog, QDialogButtonBox, QPushButton

from hexrd.ui import enter_key_filter, resource_loader

from hexrd.ui.singletons import QSingleton

import hexrd.ui.resources.ui


class UiLoader(QUiLoader, metaclass=QSingleton):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.register_custom_widgets()

    def register_custom_widgets(self):
        # Import these here to avoid circular imports
        from hexrd.ui.hidden_bar_tab_widget import HiddenBarTabWidget
        from hexrd.ui.indexing.grains_table_view import GrainsTableView
        from hexrd.ui.image_canvas import ImageCanvas
        from hexrd.ui.image_tab_widget import ImageTabWidget
        from hexrd.ui.scientificspinbox import ScientificDoubleSpinBox

        register_list = [
            GrainsTableView,
            HiddenBarTabWidget,
            ImageCanvas,
            ImageTabWidget,
            ScientificDoubleSpinBox,
        ]

        for item in register_list:
            self.registerCustomWidget(item)

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

        Currently, it installs an enter key filter for QDialogs to prevent
        the enter key from closing them.
        """
        if isinstance(ui, QDialog):
            self.install_dialog_enter_key_filters(ui)

    def install_dialog_enter_key_filters(self, dialog):
        """Block enter key press accept/reject for dialogs

        This function installs enter key filters on a QDialog and all
        QPushButton children that follow this parent/child scheme:

        QDialog -> QDialogButtonBox -> QPushButton

        The enter key filter blocks all enter/return key presses from
        automatically accepting or rejecting the dialog, to prevent
        the user from accidentally closing the dialog by pressing enter.

        The event filter must be installed both on the QDialog and the
        QPushButtons because it is currently unpredictable (to me,
        at least) which one will receive the key press event, and if the
        QDialog receives the key press event, it DOES NOT forward the
        event to the QPushButton, but rather "clicks" the QPushButton.
        """
        dialog.installEventFilter(enter_key_filter)

        for box in dialog.findChildren(QDialogButtonBox):
            for button in box.findChildren(QPushButton):
                button.installEventFilter(enter_key_filter)
