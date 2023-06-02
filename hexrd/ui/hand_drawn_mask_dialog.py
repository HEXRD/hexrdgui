from PySide2.QtCore import QObject, Signal, Qt

from itertools import cycle

import numpy as np

import matplotlib.pyplot as plt
from matplotlib.widgets import Cursor

from hexrd.ui.constants import ViewType
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import add_sample_points


class HandDrawnMaskDialog(QObject):

    # Emits the ring data that was selected
    finished = Signal(list, list)

    def __init__(self, canvas, parent):
        super(HandDrawnMaskDialog, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('hand_drawn_mask_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.canvas = canvas
        self.ring_data = []
        self.linebuilder = None
        self.lines = []
        self.drawing = False
        self.dets = []

        prop_cycle = plt.rcParams['axes.prop_cycle']
        self.color_cycler = cycle(prop_cycle.by_key()['color'])

        self.move_dialog_to_left()

        self.setup_connections()

    def setup_connections(self):
        self.ui.accepted.connect(self.accepted)
        self.ui.rejected.connect(self.rejected)
        self.bp_id = self.canvas.mpl_connect('button_press_event',
                                             self.button_pressed)
        self.enter_id = self.canvas.mpl_connect('axes_enter_event',
                                                self.axes_entered)
        self.exit_id = self.canvas.mpl_connect('axes_leave_event',
                                               self.axes_exited)

    def move_dialog_to_left(self):
        # This moves the dialog to the left border of the parent
        ph = self.ui.parent().geometry().height()
        px = self.ui.parent().geometry().x()
        py = self.ui.parent().geometry().y()
        dw = self.ui.width()
        dh = self.ui.height()
        self.ui.setGeometry(px, py + (ph - dh) / 2.0, dw, dh)

    def clear(self):
        self.ring_data.clear()

        while self.lines:
            self.lines.pop(0).remove()

        if self.linebuilder:
            self.linebuilder.disconnect()

        self.linebuilder = None
        self.cursor = None

        self.canvas.mpl_disconnect(self.bp_id)
        self.canvas.mpl_disconnect(self.enter_id)
        self.canvas.mpl_disconnect(self.exit_id)

        self.bp_id = None
        self.enter_id = None
        self.exit_id = None
        self.canvas.draw()

    def start(self):
        # list for set of rings 'picked'
        self.ring_data.clear()
        self.show()

    def axes_entered(self, event):
        if self.drawing:
            return

        self.ax = event.inaxes
        # fire up the cursor for this tool
        self.cursor = Cursor(self.ax, useblit=True, color='red', linewidth=1)
        self.add_line()

    def axes_exited(self, event):
        if not self.drawing:
            self.linebuilder.disconnect()
            self.lines.pop()

    def add_line(self):
        if self.drawing:
            return

        color = next(self.color_cycler)
        marker = '.'
        linestyle = 'None'

        # empty line
        line, = self.ax.plot([], [], color=color, marker=marker,
                        linestyle=linestyle)
        self.linebuilder = LineBuilder(line)
        self.lines.append(line)
        self.canvas.draw_idle()

    def line_finished(self):
        # append to ring_data
        linebuilder = self.linebuilder
        ring_data = np.vstack([linebuilder.xs, linebuilder.ys]).T

        if len(ring_data) == 0:
            # Don't do anything if there is no ring data
            return

        linebuilder.disconnect()

        # Make sure there are at least 50 points, so that conversions
        # between raw/polar views come out okay.
        ring_data = add_sample_points(ring_data, 50)

        self.ring_data.append(ring_data)
        self.dets.append(self.ax.get_title())
        self.drawing = False
        self.add_line()

    def button_pressed(self, event):
        if event.button == 1:
            if event.dblclick:
                self.accepted()
                self.ui.close()
                return
            self.drawing = True
        if event.button == 3:
            self.line_finished()

    def accepted(self):
        # Finish the current line
        self.line_finished()
        self.finished.emit(self.dets, self.ring_data)
        self.clear()

    def rejected(self):
        self.clear()

    def show(self):
        self.ui.show()


class LineBuilder(QObject):

    # Emits when a point was picked
    point_picked = Signal()

    def __init__(self, line):
        super().__init__()

        self.line = line
        self.canvas = line.figure.canvas
        self.xs = list(line.get_xdata())
        self.ys = list(line.get_ydata())
        self.cid = self.canvas.mpl_connect('button_press_event', self)

    def __del__(self):
        self.disconnect()

    def disconnect(self):
        if self.cid is not None:
            # Disconnect the signal
            self.canvas.mpl_disconnect(self.cid)
            self.cid = None

    def __call__(self, event):
        """
        Picker callback
        """
        print('%s click: button=%d, x=%d, y=%d, xdata=%f, ydata=%f' %
              ('double' if event.dblclick else 'single', event.button,
               event.x, event.y, event.xdata, event.ydata))

        if event.inaxes != self.line.axes:
            return

        if event.button == 1:
            self.handle_left_click(event)
        elif event.button == 2:
            self.handle_middle_click(event)

    def handle_left_click(self, event):
        self.append_data(event.xdata, event.ydata)

    def handle_middle_click(self, event):
        self.append_data(np.nan, np.nan)

    def append_data(self, x, y):
        self.xs.append(x)
        self.ys.append(y)
        self.update_line_data()
        self.point_picked.emit()

    def update_line_data(self):
        self.line.set_data(self.xs, self.ys)
        self.canvas.draw_idle()
