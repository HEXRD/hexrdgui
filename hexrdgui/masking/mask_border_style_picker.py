from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from hexrdgui.ui_loader import UiLoader


class MaskBorderStylePicker(QObject):

    def __init__(
        self,
        original_color,
        original_style,
        original_width,
        original_highlight,
        original_highlight_opacity,
        parent=None,
    ):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('mask_border_style_picker.ui', parent)
        self.original_color = original_color
        self.original_style = original_style
        self.original_width = original_width
        self.original_highlight = original_highlight
        self.original_highlight_opacity = original_highlight_opacity

        self.reset_ui()
        self.setup_connections()

    def reset_ui(self):
        self.ui.border_color.setText(self.original_color)
        self.ui.border_color.setStyleSheet(
            'QPushButton {background-color: %s}' % self.original_color
        )
        self.ui.border_style.setCurrentText(self.original_style)
        self.ui.border_size.setValue(self.original_width)
        self.ui.highlight_color.setText(self.original_highlight)
        self.ui.highlight_color.setStyleSheet(
            'QPushButton {background-color: %s}' % self.original_highlight
        )
        self.ui.opacity.setValue(self.original_highlight_opacity)

    def exec(self):
        self.ui.adjustSize()
        return self.ui.exec()

    def setup_connections(self):
        self.ui.border_color.clicked.connect(lambda: self.pick_color('border'))
        self.ui.button_box.rejected.connect(self.reject)
        self.ui.highlight_color.clicked.connect(lambda: self.pick_color('highlight'))

    @property
    def color(self):
        return self.ui.border_color.text()

    @property
    def style(self):
        return self.ui.border_style.currentText()

    @property
    def width(self):
        return self.ui.border_size.value()

    @property
    def highlight(self):
        return self.ui.highlight_color.text()

    @property
    def opacity(self):
        return self.ui.opacity.value()

    def pick_color(self, type):
        options = {
            'border': self.original_color,
            'highlight': self.original_highlight,
            'border_ui': self.ui.border_color,
            'highlight_ui': self.ui.highlight_color,
        }
        dialog = QColorDialog(QColor(options[type]), self.ui)
        if dialog.exec():
            color = dialog.selectedColor().name()
            options[f'{type}_ui'].setText(color)
            options[f'{type}_ui'].setStyleSheet(
                'QPushButton {background-color: %s}' % color
            )

    def reject(self):
        self.reset_ui()

    def result(self):
        return self.color, self.style, self.width, self.highlight, self.opacity
