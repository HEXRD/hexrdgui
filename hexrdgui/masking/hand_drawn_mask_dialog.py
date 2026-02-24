from __future__ import annotations

from typing import Any, TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QWidget

from itertools import cycle

import numpy as np

import matplotlib.pyplot as plt
from matplotlib.widgets import Cursor

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.backend_bases import (
        LocationEvent,
        MouseEvent,
    )

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import add_sample_points
from hexrdgui.utils.dialog import add_help_url
from hexrdgui.utils.matplotlib import remove_artist

# TODO: How to handle image mode? Mode has changed by
# the time the signal has been emitted.


class HandDrawnMaskDialog(QObject):

    # Emits the ring data that was selected
    finished = Signal(list, list)

    def __init__(self, canvas: Any, parent: QWidget) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('hand_drawn_mask_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.WindowType.Tool)

        add_help_url(self.ui.buttonBox, 'configuration/masking/#polygon')

        self.canvas = canvas
        self.ring_data: list[np.ndarray] = []
        self.linebuilder: LineBuilder | None = None
        self.lines: list[Any] = []
        self.drawing = False
        self.dets: list[str | None] = []
        self.det: str | None = None
        self.ax: Axes | None = None
        self.cursor: Cursor | None = None

        self.bp_id = None
        self.enter_id = None
        self.exit_id = None

        prop_cycle = plt.rcParams['axes.prop_cycle']
        self.color_cycler = cycle(prop_cycle.by_key()['color'])

        self.move_dialog_to_left()

        self.setup_connections()
        self.setup_canvas_connections()

    def setup_connections(self) -> None:
        self.ui.accepted.connect(self.accepted)
        self.ui.rejected.connect(self.rejected)

    def setup_canvas_connections(self) -> None:
        # Ensure previous canvas connections are disconnected
        self.disconnect_canvas_connections()

        self.bp_id = self.canvas.mpl_connect('button_press_event', self.button_pressed)
        self.enter_id = self.canvas.mpl_connect('axes_enter_event', self.axes_entered)
        self.exit_id = self.canvas.mpl_connect('axes_leave_event', self.axes_exited)

    def disconnect_canvas_connections(self) -> None:
        if self.bp_id:
            self.canvas.mpl_disconnect(self.bp_id)
            self.bp_id = None

        if self.enter_id:
            self.canvas.mpl_disconnect(self.enter_id)
            self.enter_id = None

        if self.exit_id:
            self.canvas.mpl_disconnect(self.exit_id)
            self.exit_id = None

    def move_dialog_to_left(self) -> None:
        # This moves the dialog to the left border of the parent
        ph = self.ui.parent().geometry().height()
        px = self.ui.parent().geometry().x()
        py = self.ui.parent().geometry().y()
        dw = self.ui.width()
        dh = self.ui.height()
        self.ui.setGeometry(px, py + (ph - dh) / 2.0, dw, dh)

    def clear(self) -> None:
        self.ring_data.clear()

        while self.lines:
            remove_artist(self.lines.pop(0))

        if self.linebuilder:
            self.linebuilder.disconnect_all()

        self.linebuilder = None
        self.cursor = None

        self.disconnect_canvas_connections()

        self.dets.clear()
        self.canvas.draw()

    def start(self) -> None:
        # list for set of rings 'picked'
        self.ring_data.clear()
        self.show()

    def axes_entered(self, event: LocationEvent) -> None:
        if self.drawing:
            return

        self.ax = event.inaxes
        assert self.ax is not None
        # Get the detector name on mask creation since completion may have been
        # triggered by the canvas being changed. No title is returned unless
        # we're in the raw view but that is the only time it is needed. See:
        # https://github.com/HEXRD/hexrdgui/blob/master/hexrd/ui/main_window.py#L727-L745
        self.det = self.ax.get_title()
        # fire up the cursor for this tool
        self.cursor = Cursor(self.ax, useblit=True, color='red', linewidth=1)
        self.add_line()

    def axes_exited(self, event: LocationEvent) -> None:
        if not self.drawing:
            if self.linebuilder:
                self.linebuilder.disconnect_all()
            if self.lines:
                self.lines.pop()

    def add_line(self) -> None:
        if self.drawing:
            return

        color = next(self.color_cycler)
        marker = '.'
        linestyle = 'None'

        # empty line
        assert self.ax is not None
        (line,) = self.ax.plot([], [], color=color, marker=marker, linestyle=linestyle)
        self.linebuilder = LineBuilder(line)
        self.lines.append(line)
        self.canvas.draw_idle()

    def line_finished(self) -> None:
        if not self.linebuilder:
            return

        # append to ring_data
        linebuilder = self.linebuilder
        ring_data = np.vstack([linebuilder.xs, linebuilder.ys]).T

        if len(ring_data) == 0:
            # Don't do anything if there is no ring data
            return

        linebuilder.disconnect_all()

        # Make sure there are at least 300 points, so that conversions
        # between raw/polar views come out okay.
        ring_data = add_sample_points(ring_data, 300)

        self.ring_data.append(ring_data)
        self.dets.append(self.det)
        self.drawing = False
        self.add_line()

    def button_pressed(self, event: MouseEvent) -> None:
        if event.button == 1:
            if event.dblclick:
                self.accepted()
                self.ui.close()
                return
            self.drawing = True
        if event.button == 3:
            self.line_finished()

    def accepted(self) -> None:
        # Finish the current line
        self.line_finished()
        self.finished.emit(self.dets, self.ring_data)
        self.clear()

    def rejected(self) -> None:
        self.clear()

    def show(self) -> None:
        self.ui.show()

    def canvas_changed(self, canvas: Any) -> None:
        self.accepted()
        self.canvas = canvas
        if self.ui.isVisible():
            self.setup_canvas_connections()


class LineBuilder(QObject):

    # Emits when a point was picked
    point_picked = Signal()

    def __init__(self, line: Any) -> None:
        super().__init__()

        self.line = line
        self.canvas = line.figure.canvas
        self.xs = list(line.get_xdata())
        self.ys = list(line.get_ydata())
        self.cid = self.canvas.mpl_connect('button_press_event', self)

    def __del__(self) -> None:
        self.disconnect_all()

    def disconnect_all(self) -> None:
        if self.cid is not None:
            # Disconnect the signal
            self.canvas.mpl_disconnect(self.cid)
            self.cid = None

    def __call__(self, event: MouseEvent) -> None:
        """
        Picker callback
        """
        if HexrdConfig().stitch_raw_roi_images:
            print(
                'Polygon masks do not yet support drawing on a stitched '
                'raw view. Please switch to an unstitched view to draw the '
                'masks.'
            )
            return

        if event.inaxes != self.line.axes:
            return

        if event.button == 1:
            self.handle_left_click(event)
        elif event.button == 2:
            self.handle_middle_click(event)

    def handle_left_click(self, event: MouseEvent) -> None:
        assert event.xdata is not None and event.ydata is not None
        self.append_data(event.xdata, event.ydata)

    def handle_middle_click(self, event: MouseEvent) -> None:
        self.append_data(np.nan, np.nan)

    def append_data(self, x: float, y: float) -> None:
        self.xs.append(x)
        self.ys.append(y)
        self.update_line_data()
        self.point_picked.emit()

    def update_line_data(self) -> None:
        self.line.set_data(self.xs, self.ys)
        self.canvas.draw_idle()
