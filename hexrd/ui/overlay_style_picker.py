import copy

from PySide2.QtCore import QObject, QSignalBlocker
from PySide2.QtGui import QColor
from PySide2.QtWidgets import QColorDialog

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class OverlayStylePicker(QObject):

    def __init__(self, overlay, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('overlay_style_picker.ui', parent)

        self.original_style = copy.deepcopy(overlay['style'])
        self.overlay = overlay
        self.ui.material_name.setText(overlay['material'])

        self.setup_labels()
        self.setup_combo_boxes()
        self.setup_connections()
        self.update_gui()

    def setup_connections(self):
        self.ui.data_color.pressed.connect(self.pick_color)
        self.ui.range_color.pressed.connect(self.pick_color)
        self.ui.data_style.currentIndexChanged.connect(self.update_config)
        self.ui.range_style.currentIndexChanged.connect(self.update_config)
        self.ui.data_size.valueChanged.connect(self.update_config)
        self.ui.range_size.valueChanged.connect(self.update_config)

        # Reset the style if the dialog is rejected
        self.ui.rejected.connect(self.reset_style)

    def setup_labels(self):
        # Override some of the labels, depending on our type
        for k, v in self.labels.items():
            # Take advantage of the naming scheme
            w = getattr(self.ui, k + '_label')
            w.setText(v)

    def setup_combo_boxes(self):
        type = self.overlay['type']

        line_styles = [
            'solid',
            'dotted',
            'dashed',
            'dashdot'
        ]

        marker_styles = [
            '.',
            'o',
            '^',
            's',
            'x',
            'D'
        ]

        if type == 'laue':
            data_styles = marker_styles
        else:
            data_styles = line_styles

        w = self.ui.data_style
        w.clear()
        for s in data_styles:
            w.addItem(s, s)

        w = self.ui.range_style
        w.clear()
        for s in line_styles:
            w.addItem(s, s)

    @property
    def style(self):
        return self.overlay['style']

    @property
    def all_widgets(self):
        return [
            self.ui.data_color,
            self.ui.data_style,
            self.ui.data_size,
            self.ui.range_color,
            self.ui.range_style,
            self.ui.range_size
        ]

    def reset_style(self):
        if self.overlay['style'] == self.original_style:
            # Nothing really to do...
            return

        self.overlay['style'] = copy.deepcopy(self.original_style)
        self.overlay['update_needed'] = True
        self.update_gui()
        HexrdConfig().overlay_config_changed.emit()

    def update_gui(self):
        data = self.style['data']
        ranges = self.style['ranges']
        keys = self.keys

        blockers = [QSignalBlocker(x) for x in self.all_widgets]
        self.ui.data_color.setText(data[keys['data_color']])
        self.ui.data_style.setCurrentText(data[keys['data_style']])
        self.ui.data_size.setValue(data[keys['data_size']])
        self.ui.range_color.setText(ranges[keys['range_color']])
        self.ui.range_style.setCurrentText(ranges[keys['range_style']])
        self.ui.range_size.setValue(ranges[keys['range_size']])

        # Unblock
        del blockers

        self.update_button_colors()

    def update_config(self):
        data = self.style['data']
        ranges = self.style['ranges']
        keys = self.keys

        data[keys['data_color']] = self.ui.data_color.text()
        data[keys['data_style']] = self.ui.data_style.currentData()
        data[keys['data_size']] = self.ui.data_size.value()
        ranges[keys['range_color']] = self.ui.range_color.text()
        ranges[keys['range_style']] = self.ui.range_style.currentData()
        ranges[keys['range_size']] = self.ui.range_size.value()
        self.overlay['update_needed'] = True
        HexrdConfig().overlay_config_changed.emit()

    def pick_color(self):
        # This should only be called by signals/slots
        # It uses the sender() to get the button that called it
        sender = self.sender()
        color = sender.text()

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec_():
            sender.setText(dialog.selectedColor().name())
            self.update_button_colors()
            self.update_config()

    def update_button_colors(self):
        buttons = [self.ui.data_color, self.ui.range_color]
        for b in buttons:
            b.setStyleSheet('QPushButton {background-color: %s}' % b.text())

    @property
    def keys(self):
        if not hasattr(self, '_keys'):
            self._keys = {
                'powder': self.powder_keys,
                'laue': self.laue_keys,
                'mono_rotation_series': self.mono_rotation_series_keys
            }

        type = self.overlay['type']
        if type not in self._keys:
            raise Exception(f'Unknown type: {type}')

        return self._keys[type]

    @property
    def powder_keys(self):
        return {
            'data_color': 'c',
            'data_style': 'ls',
            'data_size': 'lw',
            'range_color': 'c',
            'range_style': 'ls',
            'range_size': 'lw'
        }

    @property
    def laue_keys(self):
        return {
            'data_color': 'c',
            'data_style': 'marker',
            'data_size': 's',
            'range_color': 'c',
            'range_style': 'ls',
            'range_size': 'lw'
        }

    @property
    def mono_rotation_series_keys(self):
        return {
            'data_color': 'c',
            'data_style': 'ls',
            'data_size': 'lw',
            'range_color': 'c',
            'range_style': 'ls',
            'range_size': 'lw'
        }

    @property
    def labels(self):
        if not hasattr(self, '_labels'):
            self._labels = {
                'powder': self.powder_labels,
                'laue': self.laue_labels,
                'mono_rotation_series': self.mono_rotation_series_labels
            }

        type = self.overlay['type']
        if type not in self._labels:
            raise Exception(f'Unknown type: {type}')

        return self._labels[type]

    @property
    def powder_labels(self):
        # No labels to override
        return {}

    @property
    def laue_labels(self):
        return {
            'data_style': 'Marker Style:',
            'data_size': 'Marker Size:'
        }

    @property
    def mono_rotation_series_labels(self):
        # No labels to override
        return {}
