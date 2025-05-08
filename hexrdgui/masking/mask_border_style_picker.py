from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from hexrdgui.ui_loader import UiLoader


class MaskBorderStylePicker(QObject):

    def __init__(self, original_color, original_style, original_width, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('mask_border_style_picker.ui', parent)
        self.original_color = original_color
        self.original_style = original_style
        self.original_width = original_width
        self.color = original_color
        self.style = original_style
        self.width = original_width

        self.setup_ui()
        self.setup_connections()

    def setup_ui(self):
        self.ui.border_color.setText(self.original_color)
        self.ui.border_color.setStyleSheet('QPushButton {background-color: %s}' % self.original_color)
        self.ui.border_style.setCurrentText(self.original_style)
        self.ui.border_size.setValue(self.original_width)

    def exec(self):
        self.ui.adjustSize()
        return self.ui.exec()

    def setup_connections(self):
        self.ui.border_color.clicked.connect(self.pick_color)
        self.ui.border_style.currentIndexChanged.connect(self.update_style)
        self.ui.border_size.valueChanged.connect(self.update_width)
        self.ui.button_box.rejected.connect(self.reject)

    def pick_color(self):
        dialog = QColorDialog(QColor(self.original_color), self.ui)
        if dialog.exec():
            self.color = dialog.selectedColor().name()
            self.ui.border_color.setText(self.color)
            self.ui.border_color.setStyleSheet('QPushButton {background-color: %s}' % self.color)

    def update_style(self):
        self.style = self.ui.border_style.currentText()

    def update_width(self):
        self.width = self.ui.border_size.value()

    def reject(self):
        self.color = self.original_color
        self.style = self.original_style
        self.width = self.original_width

    def result(self):
        return self.color, self.style, self.width
