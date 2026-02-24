from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QDialog, QLabel, QSizePolicy, QVBoxLayout, QWidget

from matplotlib.axes import Axes
from matplotlib.backend_bases import FigureCanvasBase, KeyEvent, MouseEvent
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import numpy as np

# Line data is a list of (x, y) for each line
LineData = list[tuple[np.ndarray, np.ndarray]]


class WaterfallPlot:
    """Waterfall Plot

    This class manages button clicks and key events for interactions
    with a waterfall plot
    """

    def __init__(self, ax: Axes, line_data: LineData) -> None:
        self.ax = ax
        self.create_lines(line_data)

        self.currently_dragging: int | None = None
        self._prev_mouse_coords: np.ndarray | None = None
        self._shift_held = False

        self._mpl_cids: list[Any] = []

        self.connect()

    def create_lines(self, line_data: LineData) -> None:
        # Compute a default offset
        offset = np.nanmax([np.nanmax(y) for _, y in line_data])
        offset *= 1.05

        lines = []
        for i, (x, y) in enumerate(line_data):
            lines.append(
                self.ax.plot(
                    x,
                    y + offset * i,
                    lw=2.5,
                    label=f'Frame {i + 1}',
                )[0]
            )

        self.lines = lines

        self.ax.legend()

        # Also cache the line data for mouse interactions
        cached_line_data = []
        for line in lines:
            cached_line_data.append(np.array(line.get_data()).T)
        self._cached_line_data = cached_line_data

    @property
    def figure(self) -> Figure:
        fig = self.ax.figure
        assert isinstance(fig, Figure)
        return fig

    @property
    def canvas(self) -> FigureCanvasBase:
        return self.figure.canvas

    @property
    def _mpl_callbacks(self) -> dict[str, Callable]:
        return {
            'button_press_event': self.on_button_press,
            'button_release_event': self.on_button_release,
            'key_press_event': self.on_key_press,
            'key_release_event': self.on_key_release,
            'motion_notify_event': self.on_motion,
            'scroll_event': self.on_scroll,
        }

    def on_button_press(self, event: MouseEvent) -> None:
        if event.inaxes is not self.ax:
            return

        if self.ax.get_navigate_mode() is not None:
            # Zooming or panning is active. Ignore this click.
            return

        coords_clicked = np.array((event.xdata, event.ydata))

        # Find the closest line, and drag that one
        closest_line_idx = self._find_closest_line(coords_clicked)

        self._prev_mouse_coords = coords_clicked
        self.currently_dragging = closest_line_idx

    def on_button_release(self, event: MouseEvent) -> None:
        self.currently_dragging = None
        self._prev_mouse_coords = None
        self.canvas.draw_idle()

    def on_key_press(self, event: KeyEvent) -> None:
        if event.key == 'shift':
            self._shift_held = True

    def on_key_release(self, event: KeyEvent) -> None:
        if event.key == 'shift':
            self._shift_held = False

    def on_motion(self, event: MouseEvent) -> None:
        if self.currently_dragging is None or event.inaxes is not self.ax:
            return

        mouse_coords = np.array((event.xdata, event.ydata))
        adjustment = mouse_coords - self._prev_mouse_coords
        if not self._shift_held:
            # If shift is not held, only allow y to vary
            adjustment[0] = 0

        data = self._cached_line_data[self.currently_dragging]
        line = self.lines[self.currently_dragging]
        data += adjustment

        line.set_data(data.T)

        # Rescale the axes
        # Maybe this is something we want the user to be able to disable?
        self.ax.relim()
        self.ax.autoscale_view()

        # Redraw
        self.canvas.draw_idle()

        self._prev_mouse_coords = mouse_coords

    def on_scroll(self, event: MouseEvent) -> None:
        mouse_coords = np.array((event.xdata, event.ydata))

        # Find the closest line, and drag that one
        closest_line_idx = self._find_closest_line(mouse_coords)

        base_scale = 1.1
        if event.button == 'up':
            # Increase the data intensity
            scale_factor = base_scale
        else:
            # Decrease the data intensity
            scale_factor = 1 / base_scale

        data = self._cached_line_data[closest_line_idx]

        # Don't allow the mean to change
        mean_y = np.nanmean(data[:, 1])

        data[:, 1] = (data[:, 1] - mean_y) * scale_factor + mean_y

        line = self.lines[closest_line_idx]
        line.set_data(data.T)

        # Redraw
        self.canvas.draw_idle()

    def _find_closest_line(self, coords: np.ndarray) -> int:
        # Find the closest line to a set of coordinates and return
        # the closest line index
        min_distance = np.inf
        closest_line_idx = -1
        for i, data in enumerate(self._cached_line_data):
            distances = np.sqrt((data - coords) ** 2).sum(axis=1)
            min_dist = np.nanmin(distances)
            if min_dist < min_distance:
                min_distance = min_dist
                closest_line_idx = i

        return closest_line_idx

    def connect(self) -> None:
        for k, f in self._mpl_callbacks.items():
            cid = self.canvas.mpl_connect(k, f)
            self._mpl_cids.append(cid)

    def disconnect(self) -> None:
        for cid in self._mpl_cids:
            self.canvas.mpl_disconnect(cid)

        self._mpl_cids.clear()


class WaterfallPlotDialog(QDialog):
    def __init__(
        self, ax: Axes, line_data: LineData, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle('Waterfall Plot')

        # Add minimize, maximize, and close buttons
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        self.waterfall_plot = WaterfallPlot(ax, line_data)
        canvas = self.waterfall_plot.canvas

        layout = QVBoxLayout()
        self.setLayout(layout)

        # Add a label describing the mouse interactions
        label1 = QLabel(
            'Click and drag a plot to adjust Y. '
            'Hold shift and then click and drag a plot to adjust both X and Y.'
        )
        label2 = QLabel(
            'Hover mouse over a line and use the mouse wheel to rescale '
            'the intensities of that line'
        )
        for label in (label1, label2):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
            layout.addWidget(label)

        # Add the canvas
        canvas.figure.tight_layout()
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)  # type: ignore[attr-defined]
        layout.addWidget(canvas)  # type: ignore[arg-type]

        # Add a navigation toolbar too
        self.toolbar = NavigationToolbar(canvas, self)
        self.toolbar.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        layout.addWidget(self.toolbar)
        layout.setAlignment(self.toolbar, Qt.AlignmentFlag.AlignCenter)

    def resizeEvent(self, event: QResizeEvent) -> None:
        # We override this function because we want the matplotlib canvas
        # to also resize whenever the dialog is resized.
        super().resizeEvent(event)
        self.waterfall_plot.figure.tight_layout()


if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication

    import matplotlib.pyplot as plt

    app = QApplication()

    # Test example
    fig, ax = plt.subplots()
    data1 = np.load('example_integration.npy')
    data2 = data1.copy()
    data3 = data2.copy()

    line_data = []
    for data in (data1, data2, data3):
        line_data.append((*data.T,))

    label_kwargs: dict[str, Any] = {
        'fontsize': 15,
        'family': 'serif',
    }
    ax.set_ylabel(r'Azimuthal Average', **label_kwargs)

    polar_xlabel = r'2$\theta_{{nom}}$ [deg]'
    ax.set_xlabel(polar_xlabel, **label_kwargs)

    dialog = WaterfallPlotDialog(ax, line_data)
    dialog.show()

    app.exec()
