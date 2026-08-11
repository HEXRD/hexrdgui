import copy

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QWidget

from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class StayOutZoneEditor:
    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the stay out zone editor."""
        self._config_changed_callback = None

        loader = UiLoader()
        self.ui = loader.load_file('stay_out_zone_editor.ui', parent)

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

        # Angle connections
        self.ui.angle1.valueChanged.connect(self.on_config_changed)
        self.ui.angle2.valueChanged.connect(self.on_config_changed)

        # Circle 1 style connections
        self.ui.circle1_line_color.pressed.connect(
            lambda: self.pick_color('circle1_line_color')
        )
        self.ui.circle1_line_style.currentIndexChanged.connect(self.on_config_changed)
        self.ui.circle1_line_width.valueChanged.connect(self.on_config_changed)
        self.ui.circle1_fill_enabled.toggled.connect(
            lambda: self.on_fill_enabled_changed(1)
        )
        self.ui.circle1_fill_color.pressed.connect(
            lambda: self.pick_color('circle1_fill_color')
        )
        self.ui.circle1_fill_alpha.valueChanged.connect(self.on_config_changed)

        # Circle 2 style connections
        self.ui.circle2_line_color.pressed.connect(
            lambda: self.pick_color('circle2_line_color')
        )
        self.ui.circle2_line_style.currentIndexChanged.connect(self.on_config_changed)
        self.ui.circle2_line_width.valueChanged.connect(self.on_config_changed)
        self.ui.circle2_fill_enabled.toggled.connect(
            lambda: self.on_fill_enabled_changed(2)
        )
        self.ui.circle2_fill_color.pressed.connect(
            lambda: self.pick_color('circle2_fill_color')
        )
        self.ui.circle2_fill_alpha.valueChanged.connect(self.on_config_changed)

    def setup_combo_boxes(self) -> None:
        line_styles = ['solid', 'dashed', 'dashdot', 'dotted']
        self.ui.circle1_line_style.clear()
        self.ui.circle1_line_style.addItems(line_styles)
        self.ui.circle2_line_style.clear()
        self.ui.circle2_line_style.addItems(line_styles)

    @property
    def all_widgets(self) -> list:
        return [
            self.ui.center_x,
            self.ui.center_y,
            self.ui.angle1,
            self.ui.angle2,
            self.ui.circle1_line_color,
            self.ui.circle1_line_style,
            self.ui.circle1_line_width,
            self.ui.circle1_fill_enabled,
            self.ui.circle1_fill_color,
            self.ui.circle1_fill_alpha,
            self.ui.circle2_line_color,
            self.ui.circle2_line_style,
            self.ui.circle2_line_width,
            self.ui.circle2_fill_enabled,
            self.ui.circle2_fill_color,
            self.ui.circle2_fill_alpha,
        ]

    @staticmethod
    def default_config() -> dict:
        """Return default configuration dictionary."""
        return {
            'center_x': 0.0,
            'center_y': 0.0,
            'angle1': 21.3,
            'angle2': 18.7,
            'circle1': {
                'line_color': '#000000',
                'line_style': 'solid',
                'line_width': 1.0,
                'fill_enabled': True,
                'fill_color': '#000000',
                'fill_alpha': 0.15,
            },
            'circle2': {
                'line_color': '#000000',
                'line_style': 'solid',
                'line_width': 1.0,
                'fill_enabled': True,
                'fill_color': '#000000',
                'fill_alpha': 0.15,
            },
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

            # Angles
            self.ui.angle1.setValue(self._config['angle1'])
            self.ui.angle2.setValue(self._config['angle2'])

            # Circle 1
            c1 = self._config['circle1']
            self.ui.circle1_line_color.setText(c1['line_color'])
            self.ui.circle1_line_style.setCurrentText(c1['line_style'])
            self.ui.circle1_line_width.setValue(c1['line_width'])
            self.ui.circle1_fill_enabled.setChecked(c1['fill_enabled'])
            self.ui.circle1_fill_color.setText(c1['fill_color'])
            self.ui.circle1_fill_alpha.setValue(c1['fill_alpha'])

            # Circle 2
            c2 = self._config['circle2']
            self.ui.circle2_line_color.setText(c2['line_color'])
            self.ui.circle2_line_style.setCurrentText(c2['line_style'])
            self.ui.circle2_line_width.setValue(c2['line_width'])
            self.ui.circle2_fill_enabled.setChecked(c2['fill_enabled'])
            self.ui.circle2_fill_color.setText(c2['fill_color'])
            self.ui.circle2_fill_alpha.setValue(c2['fill_alpha'])

        self.update_button_colors()
        self.update_fill_widgets_enabled()

    def on_config_changed(self) -> None:
        """Called when any configuration parameter changes."""
        # Update center position
        self._config['center_x'] = self.ui.center_x.value()
        self._config['center_y'] = self.ui.center_y.value()

        # Update angles
        self._config['angle1'] = self.ui.angle1.value()
        self._config['angle2'] = self.ui.angle2.value()

        # Update circle 1
        c1 = self._config['circle1']
        c1['line_color'] = self.ui.circle1_line_color.text()
        c1['line_style'] = self.ui.circle1_line_style.currentText()
        c1['line_width'] = self.ui.circle1_line_width.value()
        c1['fill_enabled'] = self.ui.circle1_fill_enabled.isChecked()
        c1['fill_color'] = self.ui.circle1_fill_color.text()
        c1['fill_alpha'] = self.ui.circle1_fill_alpha.value()

        # Update circle 2
        c2 = self._config['circle2']
        c2['line_color'] = self.ui.circle2_line_color.text()
        c2['line_style'] = self.ui.circle2_line_style.currentText()
        c2['line_width'] = self.ui.circle2_line_width.value()
        c2['fill_enabled'] = self.ui.circle2_fill_enabled.isChecked()
        c2['fill_color'] = self.ui.circle2_fill_color.text()
        c2['fill_alpha'] = self.ui.circle2_fill_alpha.value()

        # Notify callback if set
        if self._config_changed_callback:
            self._config_changed_callback(self.config)

    def on_fill_enabled_changed(self, circle_num: int) -> None:
        """Called when fill enabled checkbox changes."""
        self.update_fill_widgets_enabled()
        self.on_config_changed()

    def update_fill_widgets_enabled(self) -> None:
        """Enable/disable fill widgets based on fill_enabled checkboxes."""
        # Circle 1
        enabled1 = self.ui.circle1_fill_enabled.isChecked()
        self.ui.circle1_fill_color.setEnabled(enabled1)
        self.ui.circle1_fill_alpha.setEnabled(enabled1)

        # Circle 2
        enabled2 = self.ui.circle2_fill_enabled.isChecked()
        self.ui.circle2_fill_color.setEnabled(enabled2)
        self.ui.circle2_fill_alpha.setEnabled(enabled2)

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
            self.ui.circle1_line_color,
            self.ui.circle1_fill_color,
            self.ui.circle2_line_color,
            self.ui.circle2_fill_color,
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
