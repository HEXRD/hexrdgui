import copy

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QWidget

from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class PinholeCutoffEditor:
    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the pinhole cutoff editor."""
        self._config_changed_callback = None

        loader = UiLoader()
        self.ui = loader.load_file('pinhole_cutoff_editor.ui', parent)

        # Initialize default configuration
        self._config = self.default_config()

        self.setup_combo_boxes()
        self.setup_connections()
        self.update_gui()

    def show(self) -> None:
        self.update_gui()
        self.ui.show()

    def setup_connections(self) -> None:
        # Center position connections
        self.ui.center_x.valueChanged.connect(self.on_config_changed)
        self.ui.center_y.valueChanged.connect(self.on_config_changed)

        # Opening angle connection
        self.ui.opening_angle.valueChanged.connect(self.on_config_changed)

        # Line style connections
        self.ui.line_color.pressed.connect(
            lambda: self.pick_color('line_color')
        )
        self.ui.line_style.currentIndexChanged.connect(self.on_config_changed)
        self.ui.line_width.valueChanged.connect(self.on_config_changed)

        # Fill style connections
        self.ui.fill_enabled.toggled.connect(self.on_fill_enabled_changed)
        self.ui.fill_color.pressed.connect(
            lambda: self.pick_color('fill_color')
        )
        self.ui.fill_alpha.valueChanged.connect(self.on_config_changed)

    def setup_combo_boxes(self) -> None:
        line_styles = ['solid', 'dashed', 'dashdot', 'dotted']
        self.ui.line_style.clear()
        self.ui.line_style.addItems(line_styles)

    @property
    def all_widgets(self) -> list:
        return [
            self.ui.center_x,
            self.ui.center_y,
            self.ui.opening_angle,
            self.ui.line_color,
            self.ui.line_style,
            self.ui.line_width,
            self.ui.fill_enabled,
            self.ui.fill_color,
            self.ui.fill_alpha,
        ]

    @staticmethod
    def default_config() -> dict:
        """Return default configuration dictionary."""
        return {
            'center_x': 0.0,
            'center_y': 0.0,
            'opening_angle': 65.0,
            'line_color': '#00ff00',
            'line_style': 'solid',
            'line_width': 1.0,
            'fill_enabled': True,
            'fill_color': '#00ff00',
            'fill_alpha': 0.2,
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
            # Center position
            self.ui.center_x.setValue(self._config['center_x'])
            self.ui.center_y.setValue(self._config['center_y'])

            # Opening angle
            self.ui.opening_angle.setValue(self._config['opening_angle'])

            # Line style
            self.ui.line_color.setText(self._config['line_color'])
            self.ui.line_style.setCurrentText(self._config['line_style'])
            self.ui.line_width.setValue(self._config['line_width'])

            # Fill style
            self.ui.fill_enabled.setChecked(self._config['fill_enabled'])
            self.ui.fill_color.setText(self._config['fill_color'])
            self.ui.fill_alpha.setValue(self._config['fill_alpha'])

        self.update_button_colors()
        self.update_fill_widgets_enabled()

    def on_config_changed(self) -> None:
        """Called when any configuration parameter changes."""
        # Update center position
        self._config['center_x'] = self.ui.center_x.value()
        self._config['center_y'] = self.ui.center_y.value()

        # Update opening angle
        self._config['opening_angle'] = self.ui.opening_angle.value()

        # Update line style
        self._config['line_color'] = self.ui.line_color.text()
        self._config['line_style'] = self.ui.line_style.currentText()
        self._config['line_width'] = self.ui.line_width.value()

        # Update fill style
        self._config['fill_enabled'] = self.ui.fill_enabled.isChecked()
        self._config['fill_color'] = self.ui.fill_color.text()
        self._config['fill_alpha'] = self.ui.fill_alpha.value()

        # Notify callback if set
        if self._config_changed_callback:
            self._config_changed_callback(self.config)

    def on_fill_enabled_changed(self) -> None:
        """Called when fill enabled checkbox changes."""
        self.update_fill_widgets_enabled()
        self.on_config_changed()

    def update_fill_widgets_enabled(self) -> None:
        """Enable/disable fill widgets based on fill_enabled checkbox."""
        enabled = self.ui.fill_enabled.isChecked()
        self.ui.fill_color.setEnabled(enabled)
        self.ui.fill_alpha.setEnabled(enabled)

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
        buttons = [
            self.ui.line_color,
            self.ui.fill_color,
        ]
        for b in buttons:
            style = f'QPushButton {{background-color: {b.text()}}}'
            b.setStyleSheet(style)

    def set_config_changed_callback(self, callback) -> None:
        """
        Set callback function to be called when configuration changes.

        Args:
            callback: Function with signature callback(config: dict)
        """
        self._config_changed_callback = callback
