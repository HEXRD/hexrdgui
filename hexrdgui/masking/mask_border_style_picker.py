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

        self.reset_ui()
        self.setup_connections()

    def reset_ui(self):
        self.ui.border_color.setText(self.original_color)
        self.ui.border_color.setStyleSheet('QPushButton {background-color: %s}' % self.original_color)
        self.ui.border_style.setCurrentText(self.original_style)
        self.ui.border_size.setValue(self.original_width)

    def exec(self):
        self.ui.adjustSize()
        return self.ui.exec()

    def setup_connections(self):
        self.ui.border_color.clicked.connect(self.pick_color)
        self.ui.button_box.rejected.connect(self.reject)

    @property
    def color(self):
        return self.ui.border_color.text()

    @property
    def style(self):
        return self.ui.border_style.currentText()

    @property
    def width(self):
        return self.ui.border_size.value()

    def pick_color(self):
        dialog = QColorDialog(QColor(self.original_color), self.ui)
        if dialog.exec():
            color = dialog.selectedColor().name()
            self.ui.border_color.setText(color)
            self.ui.border_color.setStyleSheet('QPushButton {background-color: %s}' % color)

    def reject(self):
        self.reset_ui()

    def result(self):
        return self.color, self.style, self.width
