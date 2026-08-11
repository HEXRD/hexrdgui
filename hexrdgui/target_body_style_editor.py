import copy

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QWidget

from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class TargetBodyStyleEditor:
    def __init__(self, body_type: str, parent: QWidget | None = None) -> None:
        """
        Initialize the target body style editor.

        Args:
            body_type: Either 'aluminum' or 'stainless_steel'
            parent: Parent widget
        """
        self.body_type = body_type
        self._style_changed_callback = None

        loader = UiLoader()
        self.ui = loader.load_file('target_body_style_editor.ui', parent)

        # Set window title based on body type
        title = f"{body_type.replace('_', ' ').title()} Body Overlay Style"
        self.ui.setWindowTitle(title)

        # Initialize default style
        self._style = self.default_style()

        self.setup_combo_boxes()
        self.setup_connections()
        self.update_gui()

    def show(self) -> None:
        self.update_gui()
        self.ui.show()

    def setup_connections(self) -> None:
        # Line style connections
        self.ui.line_color.pressed.connect(self.pick_line_color)
        self.ui.line_style.currentIndexChanged.connect(self.on_style_changed)
        self.ui.line_width.valueChanged.connect(self.on_style_changed)

        # Fill style connections
        self.ui.fill_enabled.toggled.connect(self.on_fill_enabled_changed)
        self.ui.fill_color.pressed.connect(self.pick_fill_color)
        self.ui.fill_alpha.valueChanged.connect(self.on_style_changed)

    def setup_combo_boxes(self) -> None:
        self.ui.line_style.clear()
        self.ui.line_style.addItems(self.line_style_options)

    @property
    def line_style_options(self) -> list[str]:
        """Available matplotlib line styles."""
        return [
            'solid',
            'dashed',
            'dashdot',
            'dotted',
        ]

    @property
    def all_widgets(self) -> list:
        return [
            self.ui.line_color,
            self.ui.line_style,
            self.ui.line_width,
            self.ui.fill_enabled,
            self.ui.fill_color,
            self.ui.fill_alpha,
        ]

    @staticmethod
    def default_style() -> dict:
        """Return default style dictionary."""
        return {
            'line_color': '#ff0000',
            'line_style': 'solid',
            'line_width': 2.0,
            'fill_enabled': False,
            'fill_color': '#ff0000',
            'fill_alpha': 0.3,
        }

    @property
    def style(self) -> dict:
        """Get the current style dictionary."""
        return copy.deepcopy(self._style)

    @style.setter
    def style(self, value: dict) -> None:
        """Set the style dictionary."""
        self._style = copy.deepcopy(value)
        self.update_gui()

    def update_gui(self) -> None:
        """Update GUI widgets from current style."""
        with block_signals(*self.all_widgets):
            self.ui.line_color.setText(self._style['line_color'])
            self.ui.line_style.setCurrentText(self._style['line_style'])
            self.ui.line_width.setValue(self._style['line_width'])
            self.ui.fill_enabled.setChecked(self._style['fill_enabled'])
            self.ui.fill_color.setText(self._style['fill_color'])
            self.ui.fill_alpha.setValue(self._style['fill_alpha'])

        self.update_button_colors()
        self.update_fill_widgets_enabled()

    def on_style_changed(self) -> None:
        """Called when any style parameter changes."""
        self._style['line_color'] = self.ui.line_color.text()
        self._style['line_style'] = self.ui.line_style.currentText()
        self._style['line_width'] = self.ui.line_width.value()
        self._style['fill_enabled'] = self.ui.fill_enabled.isChecked()
        self._style['fill_color'] = self.ui.fill_color.text()
        self._style['fill_alpha'] = self.ui.fill_alpha.value()

        # Notify callback if set
        if self._style_changed_callback:
            self._style_changed_callback(self.body_type, self.style)

    def on_fill_enabled_changed(self) -> None:
        """Called when fill enabled checkbox changes."""
        self.update_fill_widgets_enabled()
        self.on_style_changed()

    def update_fill_widgets_enabled(self) -> None:
        """Enable/disable fill widgets based on fill_enabled checkbox."""
        enabled = self.ui.fill_enabled.isChecked()
        self.ui.fill_color.setEnabled(enabled)
        self.ui.fill_alpha.setEnabled(enabled)

    def pick_line_color(self) -> None:
        """Open color picker for line color."""
        w = self.ui.line_color
        color = w.text()

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec():
            w.setText(dialog.selectedColor().name())
            self.update_button_colors()
            self.on_style_changed()

    def pick_fill_color(self) -> None:
        """Open color picker for fill color."""
        w = self.ui.fill_color
        color = w.text()

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec():
            w.setText(dialog.selectedColor().name())
            self.update_button_colors()
            self.on_style_changed()

    def update_button_colors(self) -> None:
        """Update button background colors to match selected colors."""
        # Line color button
        b = self.ui.line_color
        style = f'QPushButton {{background-color: {b.text()}}}'
        b.setStyleSheet(style)

        # Fill color button
        b = self.ui.fill_color
        style = f'QPushButton {{background-color: {b.text()}}}'
        b.setStyleSheet(style)

    def set_style_changed_callback(self, callback) -> None:
        """
        Set callback function to be called when style changes.

        Args:
            callback: Function with signature callback(body_type: str, style: dict)
        """
        self._style_changed_callback = callback
