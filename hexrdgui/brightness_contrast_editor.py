from typing import Any

import numpy as np
from scipy.interpolate import interp1d

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.container import BarContainer
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from hexrdgui.range_widget import RangeWidget
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals, reversed_enumerate


NUM_INCREMENTS = 1000

HISTOGRAM_NUM_BINS = 100


class BrightnessContrastEditor(QObject):

    edited = Signal(float, float)

    reset = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._data_range = (0, 1)
        self._ui_min: Any = 0
        self._ui_max: Any = 1
        self._ui_min, self._ui_max = self._data_range
        self._data = None
        self.histogram: Any = None
        self.histogram_artist: BarContainer | None = None
        self.line_artist: Line2D | None = None

        self.default_auto_threshold = 5000
        self.current_auto_threshold = self.default_auto_threshold

        loader = UiLoader()
        self.ui = loader.load_file('brightness_contrast_editor.ui', parent)

        self.setup_plot()

        self.ui.minimum.setMaximum(NUM_INCREMENTS)
        self.ui.maximum.setMaximum(NUM_INCREMENTS)
        self.ui.brightness.setMaximum(NUM_INCREMENTS)
        self.ui.contrast.setMaximum(NUM_INCREMENTS)

        self.setup_connections()

    def setup_connections(self) -> None:
        self.ui.minimum.valueChanged.connect(self.minimum_edited)
        self.ui.maximum.valueChanged.connect(self.maximum_edited)
        self.ui.brightness.valueChanged.connect(self.brightness_edited)
        self.ui.contrast.valueChanged.connect(self.contrast_edited)

        self.ui.set_data_range.pressed.connect(self.select_data_range)
        self.ui.reset.pressed.connect(self.reset_pressed)
        self.ui.auto_button.pressed.connect(self.auto_pressed)

    @property
    def data_range(self) -> tuple:
        return self._data_range

    @data_range.setter
    def data_range(self, v: tuple) -> None:
        self._data_range = v
        self.clip_ui_range()
        self.ensure_min_max_space('max')
        self.update_gui()

    @property
    def data(self) -> Any:
        return self._data

    @data.setter
    def data(self, v: Any) -> None:
        self._data = v
        self.reset_data_range()

    @property
    def data_list(self) -> list:
        if self.data is None:
            return []
        elif isinstance(self.data, (tuple, list)):
            return list(self.data)
        elif isinstance(self.data, dict):
            return list(self.data.values())
        else:
            return [self.data]

    @property
    def data_bounds(self) -> tuple:
        if self.data is None:
            return (0, 1)

        data = self.data_list
        mins = [np.nanmin(x) for x in data]
        maxes = [np.nanmax(x) for x in data]
        return (min(mins), max(maxes))

    def reset_data_range(self) -> None:
        self.data_range = self.data_bounds

    def update_gui(self) -> None:
        self.update_brightness()
        self.update_contrast()
        self.update_histogram()
        self.update_range_labels()
        self.update_line()

    @property
    def data_min(self) -> float:
        return self.data_range[0]

    @property
    def data_max(self) -> float:
        return self.data_range[1]

    @property
    def data_mean(self) -> float:
        return np.mean(self.data_range)

    @property
    def data_width(self) -> float:
        return self.data_range[1] - self.data_range[0]

    @property
    def ui_min(self) -> float:
        return self._ui_min

    @ui_min.setter
    def ui_min(self, v: float) -> None:
        self._ui_min = v
        slider_v = np.interp(v, self.data_range, (0, NUM_INCREMENTS))
        self.ui.minimum.setValue(slider_v)
        self.update_range_labels()
        self.update_line()
        self.modified()

    @property
    def ui_max(self) -> float:
        return self._ui_max

    @ui_max.setter
    def ui_max(self, v: float) -> None:
        self._ui_max = v
        slider_v = np.interp(v, self.data_range, (0, NUM_INCREMENTS))
        self.ui.maximum.setValue(slider_v)
        self.update_range_labels()
        self.update_line()
        self.modified()

    def clip_ui_range(self) -> None:
        # Clip the ui min and max to be in the data range
        if self.ui_min < self.data_min:
            self.ui_min = self.data_min

        if self.ui_max > self.data_max:
            self.ui_max = self.data_max

    @property
    def ui_mean(self) -> float:
        return float(np.mean((self.ui_min, self.ui_max)))

    @ui_mean.setter
    def ui_mean(self, v: float) -> None:
        offset = v - self.ui_mean
        self.ui_range = (self.ui_min + offset, self.ui_max + offset)

    @property
    def ui_width(self) -> float:
        return self.ui_max - self.ui_min

    @ui_width.setter
    def ui_width(self, v: float) -> None:
        offset = (v - self.ui_width) / 2
        self.ui_range = (self.ui_min - offset, self.ui_max + offset)

    @property
    def ui_range(self) -> tuple:
        return (self.ui_min, self.ui_max)

    @ui_range.setter
    def ui_range(self, v: tuple) -> None:
        with block_signals(self, self.ui.minimum, self.ui.maximum):
            self.ui_min = v[0]
            self.ui_max = v[1]

        self.modified()

    @property
    def ui_brightness(self) -> float:
        return self.ui.brightness.value() / NUM_INCREMENTS * 100

    @ui_brightness.setter
    def ui_brightness(self, v: float) -> None:
        self.ui.brightness.setValue(v / 100 * NUM_INCREMENTS)

    @property
    def ui_contrast(self) -> float:
        return self.ui.contrast.value() / NUM_INCREMENTS * 100

    @ui_contrast.setter
    def ui_contrast(self, v: float) -> None:
        self.ui.contrast.setValue(v / 100 * NUM_INCREMENTS)

    @property
    def contrast(self) -> float:
        angle = np.arctan((self.ui_width - self.data_width) / self.data_width)
        return float(100 - np.interp(angle, (-np.pi / 4, np.pi / 4), (0, 100)))

    @contrast.setter
    def contrast(self, v: float) -> None:
        angle = np.interp(100 - v, (0, 100), (-np.pi / 4, np.pi / 4))
        self.ui_width = float(np.tan(angle) * self.data_width + self.data_width)

    @property
    def brightness(self) -> float:
        return float(100 - np.interp(self.ui_mean, self.data_range, (0, 100)))

    @brightness.setter
    def brightness(self, v: float) -> None:
        self.ui_mean = float(np.interp(100 - v, (0, 100), self.data_range))

    def ensure_min_max_space(self, one_to_change: str) -> None:
        # Keep the maximum at least one increment ahead of the minimum
        if self.ui.maximum.value() > self.ui.minimum.value():
            return

        if one_to_change == 'max':
            w = self.ui.maximum
            v = self.ui.minimum.value() + 1
            a = '_ui_max'
        else:
            w = self.ui.minimum
            v = self.ui.maximum.value() - 1
            a = '_ui_min'

        with block_signals(w):
            w.setValue(v)

        interpolated = np.interp(v, (0, NUM_INCREMENTS), self.data_range)
        setattr(self, a, interpolated)

    def minimum_edited(self) -> None:
        v = self.ui.minimum.value()
        self._ui_min = np.interp(v, (0, NUM_INCREMENTS), self.data_range)
        self.clip_ui_range()
        self.ensure_min_max_space('max')

        self.update_brightness()
        self.update_contrast()
        self.update_range_labels()
        self.update_line()
        self.modified()

    def maximum_edited(self) -> None:
        v = self.ui.maximum.value()
        self._ui_max = np.interp(v, (0, NUM_INCREMENTS), self.data_range)
        self.clip_ui_range()
        self.ensure_min_max_space('min')

        self.update_brightness()
        self.update_contrast()
        self.update_range_labels()
        self.update_line()
        self.modified()

    def update_brightness(self) -> None:
        with block_signals(self, self.ui.brightness):
            self.ui_brightness = self.brightness

    def update_contrast(self) -> None:
        with block_signals(self, self.ui.contrast):
            self.ui_contrast = self.contrast

    def brightness_edited(self, v: float) -> None:
        self.brightness = self.ui_brightness
        self.update_contrast()

    def contrast_edited(self, v: float) -> None:
        self.contrast = self.ui_contrast
        self.update_brightness()

    def modified(self) -> None:
        self.edited.emit(self.ui_min, self.ui_max)

    def setup_plot(self) -> None:
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.axis = self.figure.add_subplot(111)

        self.figure.tight_layout()

        self.ui.plot_layout.addWidget(self.canvas)

    def clear_plot(self) -> None:
        self.axis.clear()
        self.histogram_artist = None
        self.line_artist = None

    def update_histogram(self) -> None:
        # Clear the plot so everything will be re-drawn from scratch
        self.clear_plot()

        data = self.data_list
        if not data:
            return

        histograms = []
        for datum in data:
            kwargs = {
                'a': datum,
                'bins': HISTOGRAM_NUM_BINS,
                'range': self.data_range,
            }
            hist, bins = np.histogram(**kwargs)
            histograms.append(hist)

        # Plot the histogram
        # Matplotlib's hist() function performs a histogram and THEN
        # plots it. But we already have a histogram, so just use bar()
        # instead.
        self.histogram = sum(histograms)
        kwargs = {
            'x': np.arange(HISTOGRAM_NUM_BINS),
            'height': self.histogram,
            'width': 1.0,
            'color': 'black',
            'align': 'edge',
        }
        self.histogram_artist = self.axis.bar(**kwargs)

        # Remove x margins
        self.axis.margins(x=0)

        # Hide the axes
        self.axis.xaxis.set_visible(False)
        self.axis.yaxis.set_visible(False)

        self.canvas.draw()

    def update_range_labels(self) -> None:
        labels = (self.ui.min_label, self.ui.max_label)
        texts = [f'{x:.2f}' for x in self.ui_range]
        for label, text in zip(labels, texts):
            label.setText(text)

    def create_line(self) -> None:
        xs = (self.ui_min, self.ui_max)
        ys = self.axis.get_ylim()
        kwargs: dict[str, Any] = {
            'scalex': False,
            'scaley': False,
            'color': 'black',
        }
        (self.line_artist,) = self.axis.plot(xs, ys, **kwargs)

    def update_line(self) -> None:
        if self.line_artist is None:
            self.create_line()

        assert self.line_artist is not None
        xs = (self.ui_min, self.ui_max)
        ys = self.axis.get_ylim()

        xlim = self.axis.get_xlim()

        # Rescale the xs to be in the plot scaling
        interp = interp1d(self.data_range, xlim, fill_value='extrapolate')

        self.line_artist.set_data(interp(xs), ys)
        self.canvas.draw_idle()

    @property
    def max_num_pixels(self) -> int:
        return max(np.prod(x.shape) for x in self.data_list)

    def select_data_range(self) -> None:
        dialog = QDialog(self.ui)
        layout = QVBoxLayout()
        dialog.setLayout(layout)

        range_widget = RangeWidget(dialog)
        range_widget.bounds = self.data_bounds
        range_widget.min = self.data_range[0]
        range_widget.max = self.data_range[1]
        layout.addWidget(range_widget.ui)

        buttons = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        button_box = QDialogButtonBox(buttons, dialog)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        UiLoader().install_dialog_enter_key_filters(dialog)

        if not dialog.exec():
            # User canceled
            return

        data_range = range_widget.range
        if data_range[0] >= data_range[1]:
            message = 'Min cannot be greater than or equal to the max'
            QMessageBox.critical(self.ui, 'Validation Error', message)
            return

        if self.data_range == data_range:
            # Nothing changed...
            return

        self.data_range = data_range
        self.modified()

    def reset_pressed(self) -> None:
        self.reset_data_range()
        self.reset_auto_threshold()
        self.reset.emit()

    def reset_auto_threshold(self) -> None:
        self.current_auto_threshold = self.default_auto_threshold

    def auto_pressed(self) -> None:
        data_range = self.data_range
        hist = self.histogram

        if hist is None:
            return

        # FIXME: should we do something other than max_num_pixels?
        pixel_count = self.max_num_pixels
        num_bins = len(hist)
        hist_start = data_range[0]
        bin_size = self.data_width / num_bins
        auto_threshold = self.current_auto_threshold

        # Perform the operation as ImageJ does it
        if auto_threshold < 10:
            auto_threshold = self.default_auto_threshold
        else:
            auto_threshold //= 2

        self.current_auto_threshold = auto_threshold

        limit = pixel_count / 10
        threshold = pixel_count / auto_threshold
        for i, count in enumerate(hist):
            if threshold < count <= limit:
                break

        h_min = i

        for i, count in reversed_enumerate(hist):
            if threshold < count <= limit:
                break

        h_max = i

        if h_max < h_min:
            # Reset the range
            self.reset_auto_threshold()
            self.ui_range = self.data_range
        else:
            vmin = hist_start + h_min * bin_size
            vmax = hist_start + h_max * bin_size
            if vmin == vmax:
                vmin, vmax = data_range

            self.ui_range = vmin, vmax

        self.update_brightness()
        self.update_contrast()
