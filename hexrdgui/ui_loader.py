from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QObject
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QWidget

from hexrdgui import enter_key_filter, resource_loader

from hexrdgui.singletons import QSingleton

import hexrdgui.resources.ui


class UiLoader(QUiLoader, metaclass=QSingleton):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.register_custom_widgets()

    def register_custom_widgets(self) -> None:
        # Import these here to avoid circular imports
        from hexrdgui.hidden_bar_tab_widget import HiddenBarTabWidget
        from hexrdgui.indexing.grains_table_view import GrainsTableView
        from hexrdgui.image_canvas import ImageCanvas
        from hexrdgui.image_tab_widget import ImageTabWidget
        from hexrdgui.scientificspinbox import ScientificDoubleSpinBox

        register_list = [
            GrainsTableView,
            HiddenBarTabWidget,
            ImageCanvas,
            ImageTabWidget,
            ScientificDoubleSpinBox,
        ]

        for item in register_list:
            self.registerCustomWidget(item)

    def load_file(self, file_name: str, parent: QWidget | None = None) -> Any:
        """Load a UI file and return the widget

        Returns a widget created from the UI file.

        :param file_name: The name of the ui file to load (must be located
                          in hexrd.resources.ui).
        """
        text = resource_loader.load_resource(hexrdgui.resources.ui, file_name)
        assert isinstance(text, str)
        return self.load_string(text, parent)

    def load_string(self, string: str, parent: QWidget | None = None) -> Any:
        """Load a UI file from a string and return the widget"""
        data = QByteArray(string.encode('utf-8'))
        buf = QBuffer(data)
        ui = self.load(buf, parent)

        # Perform any custom processing on the ui
        self.process_ui(ui)
        return ui

    def process_ui(self, ui: QWidget) -> None:
        """Perform any additional processing on loaded UI objects

        Currently, it installs an enter key filter for QDialogs to prevent
        the enter key from closing them.
        """
        if isinstance(ui, QDialog):
            self.install_dialog_enter_key_filters(ui)

    def install_dialog_enter_key_filters(self, dialog: QDialog) -> None:
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
