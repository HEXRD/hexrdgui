import copy

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QWidget

from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class FiddleAxesEditor:
    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the FIDDLE axes editor."""
        self._config_changed_callback = None

        loader = UiLoader()
        self.ui = loader.load_file('fiddle_axes_editor.ui', parent)

        # Initialize default configuration
        self._config = self.default_config()

        self.setup_combo_boxes()
        self.setup_connections()
        self.update_gui()

    def show(self) -> None:
        self.update_gui()
        self.ui.show()

    def setup_connections(self) -> None:
        # Origin position connections
        self.ui.origin_x.valueChanged.connect(self.on_config_changed)
        self.ui.origin_y.valueChanged.connect(self.on_config_changed)

        # Axes length connection
        self.ui.axes_length.valueChanged.connect(self.on_config_changed)

        # Axes style connections
        self.ui.axes_color.pressed.connect(
            lambda: self.pick_color('axes_color')
        )
        self.ui.axes_style.currentIndexChanged.connect(self.on_config_changed)
        self.ui.axes_width.valueChanged.connect(self.on_config_changed)

    def setup_combo_boxes(self) -> None:
        line_styles = ['solid', 'dashed', 'dashdot', 'dotted']
        self.ui.axes_style.clear()
        self.ui.axes_style.addItems(line_styles)

    @property
    def all_widgets(self) -> list:
        return [
            self.ui.origin_x,
            self.ui.origin_y,
            self.ui.axes_length,
            self.ui.axes_color,
            self.ui.axes_style,
            self.ui.axes_width,
        ]

    @staticmethod
    def default_config() -> dict:
        """Return default configuration dictionary."""
        return {
            'origin_x': 0.0,
            'origin_y': 0.0,
            'axes_length': 50.0,
            'color': '#ff0000',  # Red
            'style': 'solid',
            'width': 2.0,
        }

    @property
    def config(self) -> dict:
        """Get the current configuration dictionary."""
        return copy.deepcopy(self._config)

    @config.setter
    def config(self, value: dict) -> None:
        """Set the configuration dictionary."""
        self._config = copy.deepcopy(value)
        self.update_gui()

    def update_gui(self) -> None:
        """Update GUI widgets from current configuration."""
        with block_signals(*self.all_widgets):
            # Origin position
            self.ui.origin_x.setValue(self._config['origin_x'])
            self.ui.origin_y.setValue(self._config['origin_y'])

            # Axes length
            self.ui.axes_length.setValue(self._config['axes_length'])

            # Axes style
            self.ui.axes_color.setText(self._config['color'])
            self.ui.axes_style.setCurrentText(self._config['style'])
            self.ui.axes_width.setValue(self._config['width'])

        self.update_button_colors()

    def on_config_changed(self) -> None:
        """Called when any configuration parameter changes."""
        # Update origin position
        self._config['origin_x'] = self.ui.origin_x.value()
        self._config['origin_y'] = self.ui.origin_y.value()

        # Update axes length
        self._config['axes_length'] = self.ui.axes_length.value()

        # Update axes style
        self._config['color'] = self.ui.axes_color.text()
        self._config['style'] = self.ui.axes_style.currentText()
        self._config['width'] = self.ui.axes_width.value()

        # Notify callback if set
        if self._config_changed_callback:
            self._config_changed_callback(self.config)

    def pick_color(self, widget_name: str) -> None:
        """Open color picker for the specified widget."""
        w = getattr(self.ui, widget_name)
        color = w.text()

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec():
            w.setText(dialog.selectedColor().name())
            self.update_button_colors()
            self.on_config_changed()

    def update_button_colors(self) -> None:
        """Update button background colors to match selected colors."""
        button = self.ui.axes_color
        style = f'QPushButton {{background-color: {button.text()}}}'
        button.setStyleSheet(style)

    def set_config_changed_callback(self, callback) -> None:
        """
        Set callback function to be called when configuration changes.

        Args:
            callback: Function with signature callback(config: dict)
        """
        self._config_changed_callback = callback
