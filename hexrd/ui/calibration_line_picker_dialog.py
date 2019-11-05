from PySide2.QtCore import QObject, Signal

from itertools import cycle

import numpy as np

import matplotlib.pyplot as plt
from matplotlib.widgets import Cursor

from hexrd.ui.ui_loader import UiLoader


class CalibrationLinePickerDialog(QObject):

    # Emits the ring data that was selected
    finished = Signal(list)

    def __init__(self, canvas, parent=None):
        super(CalibrationLinePickerDialog, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('calibration_line_picker_dialog.ui', parent)

        self.canvas = canvas
        self.ring_data = []
        self.linebuilder = None
        self.lines = []

        prop_cycle = plt.rcParams['axes.prop_cycle']
        self.color_cycler = cycle(prop_cycle.by_key()['color'])

        self.setup_connections()

    def setup_connections(self):
        self.ui.accepted.connect(self.accepted)
        self.ui.rejected.connect(self.rejected)
        self.bp_id = self.canvas.mpl_connect('button_press_event',
                                             self.button_pressed)

    def clear(self):
        self.ring_data.clear()

        while self.lines:
            self.lines.pop(0).remove()

        if self.linebuilder:
            self.linebuilder.disconnect()

        self.linebuilder = None
        self.cursor = None

        self.canvas.mpl_disconnect(self.bp_id)
        self.bp_id = None
        self.canvas.draw()

    def start(self):
        if self.canvas.mode != 'polar':
            print('calibration picker only works in polar mode!')
            return

        ax = self.canvas.axis

        # list for set of rings 'picked'
        self.ring_data.clear()

        # fire up the cursor for this tool
        self.cursor = Cursor(ax, useblit=True, color='red', linewidth=1)
        self.add_line()
        self.show()

    def add_line(self):
        ax = self.canvas.axis
        color = next(self.color_cycler)
        marker = '.'
        linestyle = 'None'

        # empty line
        line, = ax.plot([], [], color=color, marker=marker,
                        linestyle=linestyle)
        self.linebuilder = LineBuilder(line)
        self.lines.append(line)
        self.canvas.draw()

    def line_finished(self):
        # append to ring_data
        linebuilder = self.linebuilder
        ring_data = np.vstack([linebuilder.xs, linebuilder.ys]).T

        if len(ring_data) == 0:
            # Don't do anything if there is no ring data
            return

        linebuilder.disconnect()
        self.ring_data.append(ring_data)
        self.add_line()

    def button_pressed(self, event):
        if event.button == 3:
            self.line_finished()

    def accepted(self):
        # Finish the current line
        self.line_finished()
        self.finished.emit(self.ring_data)
        self.clear()

    def rejected(self):
        self.clear()

    def show(self):
        self.ui.show()


class LineBuilder:
    def __init__(self, line):
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

        if event.button != 1:
            # Don't do anything unless it is a left click
            return

        if event.inaxes != self.line.axes:
            return

        self.xs.append(event.xdata)
        self.ys.append(event.ydata)
        self.line.set_data(self.xs, self.ys)
        self.canvas.draw()
