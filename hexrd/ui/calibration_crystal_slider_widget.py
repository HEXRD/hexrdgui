from enum import IntEnum

from PySide2.QtCore import QObject, QSignalBlocker, Signal
from PySide2.QtWidgets import QProxyStyle, QStyle

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class SpinBoxStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        """Increase the auto-repeat threshold to 1 sec.

        Otherwise single click causes two increments.
        """
        if hint == QStyle.SH_SpinBox_ClickAutoRepeatThreshold:
            return 1000
        else:
            return super().styleHint(hint, option, widget, returnData)


class WidgetMode(IntEnum):
    ORIENTATION = 1  # sliders update orientation
    POSITION = 2     # sliders update position


class CalibrationCrystalSliderWidget(QObject):
    changed = Signal(int, int, float)

    # Conversions from configuration value to slider value and back
    CONF_VAL_TO_SLIDER_VAL = 10
    SLIDER_VAL_TO_CONF_VAL = 0.1

    def __init__(self, parent=None):
        super(CalibrationCrystalSliderWidget, self).__init__(parent)
        self._mode = WidgetMode.ORIENTATION

        loader = UiLoader()
        self.ui = loader.load_file(
            'calibration_crystal_slider_widget.ui', parent)
        for w in self.spinbox_widgets:
            w.setStyle(SpinBoxStyle())

        self._orientation = [0.0] * 3
        self._orientatin_range = 30.0
        self._orientation_suffix = ''
        self._position = [0.0] * 3
        self._position_range = 30.0

        self.setup_connections()

    @property
    def mode(self):
        index = self.ui.slider_mode.currentIndex()
        if index == 0:
            return WidgetMode.ORIENTATION
        elif index == 1:
            return WidgetMode.POSITION
        # (else)
        raise RuntimeError(f'Unexpected mode index ${index}')

    @property
    def orientation(self):
        return self._orientation

    @property
    def position(self):
        return self._position

    @property
    def slider_widgets(self):
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'slider_{i}') for i in range(3)]

    @property
    def spinbox_widgets(self):
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'spinbox_{i}') for i in range(3)]

    def on_mode_changed(self):
        if self.mode == WidgetMode.ORIENTATION:
            data = self._orientation
            srange = self._orientation_range
            suffix = self._orientation_suffix
        else:
            data = self._position
            srange = self._position_range
            suffix = ''

        # Update spinbox values
        for i, w in enumerate(self.spinbox_widgets):
            blocker = QSignalBlocker(w)  # noqa: F841
            w.setSuffix(suffix)
            w.setValue(data[i])

        # Update slider positions
        self.ui.slider_range.setValue(srange)
        self.ui.slider_range.setSuffix(suffix)
        self.update_ranges()

    def on_slider_changed(self, value):
        sender_name = self.sender().objectName()
        index = int(sender_name[-1])
        spinbox_value = value * self.SLIDER_VAL_TO_CONF_VAL
        w_name = f'spinbox_{index}'
        w = getattr(self.ui, w_name)
        w.setValue(spinbox_value)

    def on_range_changed(self):
        self.update_ranges()

    def on_spinbox_changed(self, value):
        sender_name = self.sender().objectName()
        index = int(sender_name[-1])
        mode = self.mode
        if mode == WidgetMode.ORIENTATION:
            self._orientation[index] = value
        else:
            self._position[index] = value

        # Update slider
        slider_value = value * self.CONF_VAL_TO_SLIDER_VAL
        w_name = f'slider_{index}'
        w = getattr(self.ui, w_name)
        blocker = QSignalBlocker(w)  # noqa: F841
        w.setValue(slider_value)

        self.changed.emit(mode.value, index, value)

    def reset_ranges(self):
        self._orientation_range = 30.0
        self._position_range = 30.0
        self.update_ranges()

    def setup_connections(self):
        self.ui.slider_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.ui.slider_range.valueChanged.connect(self.on_range_changed)
        for w in self.spinbox_widgets:
            w.valueChanged.connect(self.on_spinbox_changed)
        for w in self.slider_widgets:
            w.valueChanged.connect(self.on_slider_changed)

    def set_orientation_suffix(self, suffix):
        self._orientation_suffix = suffix
        if self.mode == WidgetMode.ORIENTATION:
            self.ui.slider_range.setSuffix(suffix)
            for w in self.spinbox_widgets:
                w.setSuffix(suffix)

    def update_gui(self, orientation, position):
        """Called by parent widget."""
        self._orientation = orientation
        self._position = position

        data = self._orientation if self.mode == WidgetMode.ORIENTATION \
            else self._position
        for i, w in enumerate(self.spinbox_widgets):
            blocker = QSignalBlocker(w)  # noqa: F841
            w.setValue(data[i])
        self.update_ranges()

    def update_ranges(self):
        data = self._orientation if self.mode == WidgetMode.ORIENTATION \
            else self._position
        range_value = self.ui.slider_range.value() * \
            self.CONF_VAL_TO_SLIDER_VAL
        delta = range_value / 2.0
        sliders = self.slider_widgets
        for i, slider in enumerate(sliders):
            val = data[i]
            blocker = QSignalBlocker(slider)  # noqa: F841
            slider.setRange(val - delta, val + delta)
            slider.setValue(val)
