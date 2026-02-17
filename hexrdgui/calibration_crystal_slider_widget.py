from enum import IntEnum
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QProxyStyle, QStyle, QWidget

from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class SpinBoxStyle(QProxyStyle):
    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: Any = None,
        widget: Any = None,
        returnData: Any = None,
    ) -> int:
        """Increase the auto-repeat threshold to 1 sec.

        Otherwise single click causes two increments.
        """
        if hint == QStyle.StyleHint.SH_SpinBox_ClickAutoRepeatThreshold:
            return 1000
        else:
            return super().styleHint(hint, option, widget, returnData)


class WidgetMode(IntEnum):
    ORIENTATION = 1  # sliders update orientation
    POSITION = 2  # sliders update position


class CalibrationCrystalSliderWidget(QObject):
    changed = Signal(int, int, float)

    DEFAULT_SLIDER_RANGE = 30.0

    # Conversions from configuration value to slider value and back
    CONF_VAL_TO_SLIDER_VAL = 10
    SLIDER_VAL_TO_CONF_VAL = 0.1

    def __init__(self, parent: QWidget | None = None) -> None:
        super(CalibrationCrystalSliderWidget, self).__init__(parent)
        self._mode = WidgetMode.ORIENTATION

        loader = UiLoader()
        self.ui = loader.load_file('calibration_crystal_slider_widget.ui', parent)
        for w in self.spinbox_widgets:
            w.setStyle(SpinBoxStyle())

        self._orientation = [0.0] * 3
        self._orientation_range = self.DEFAULT_SLIDER_RANGE
        self._orientation_suffix = ''
        self._position = [0.0] * 3
        self._position_range = self.DEFAULT_SLIDER_RANGE

        self.setup_connections()

    @property
    def mode(self) -> WidgetMode:
        index = self.ui.slider_mode.currentIndex()
        if index == 0:
            return WidgetMode.ORIENTATION
        elif index == 1:
            return WidgetMode.POSITION
        # (else)
        raise RuntimeError(f'Unexpected mode index ${index}')

    @property
    def orientation(self) -> list:
        return self._orientation

    @property
    def position(self) -> list:
        return self._position

    @property
    def slider_widgets(self) -> list:
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'slider_{i}') for i in range(3)]

    @property
    def spinbox_widgets(self) -> list:
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'spinbox_{i}') for i in range(3)]

    def on_mode_changed(self) -> None:
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
            with block_signals(w):
                w.setSuffix(suffix)
                w.setValue(data[i])

        # Update slider positions
        self.ui.slider_range.setValue(srange)
        self.ui.slider_range.setSuffix(suffix)
        self.update_ranges()

    def on_slider_changed(self, value: int) -> None:
        sender_name = self.sender().objectName()
        index = int(sender_name[-1])
        spinbox_value = value * self.SLIDER_VAL_TO_CONF_VAL
        w_name = f'spinbox_{index}'
        w = getattr(self.ui, w_name)
        w.setValue(spinbox_value)

    def on_range_changed(self) -> None:
        self.update_ranges()

    def on_spinbox_changed(self, value: float) -> None:
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
        with block_signals(w):
            w.setValue(slider_value)
            self.changed.emit(mode.value, index, value)

    def reset_ranges(self) -> None:
        self._orientation_range = self.DEFAULT_SLIDER_RANGE
        self._position_range = self.DEFAULT_SLIDER_RANGE
        self.update_ranges()

    def setup_connections(self) -> None:
        self.ui.slider_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.ui.slider_range.valueChanged.connect(self.on_range_changed)
        for w in self.spinbox_widgets:
            w.valueChanged.connect(self.on_spinbox_changed)
        for w in self.slider_widgets:
            w.valueChanged.connect(self.on_slider_changed)

    def set_orientation_suffix(self, suffix: str) -> None:
        self._orientation_suffix = suffix
        if self.mode == WidgetMode.ORIENTATION:
            self.ui.slider_range.setSuffix(suffix)
            for w in self.spinbox_widgets:
                w.setSuffix(suffix)

    def update_gui(self, orientation: list, position: list) -> None:
        """Called by parent widget."""
        self._orientation = orientation
        self._position = position

        data = (
            self._orientation if self.mode == WidgetMode.ORIENTATION else self._position
        )
        for i, w in enumerate(self.spinbox_widgets):
            with block_signals(w):
                w.setValue(data[i])
        self.update_ranges()

    def update_ranges(self) -> None:
        data = (
            self._orientation if self.mode == WidgetMode.ORIENTATION else self._position
        )
        range_value = self.ui.slider_range.value() * self.CONF_VAL_TO_SLIDER_VAL
        delta = range_value / 2.0
        sliders = self.slider_widgets
        for i, slider in enumerate(sliders):
            val = data[i] * self.CONF_VAL_TO_SLIDER_VAL
            with block_signals(slider):
                slider.setRange(val - delta, val + delta)
                slider.setValue(val)
