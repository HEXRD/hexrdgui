from PySide2.QtCore import Qt, QObject, Signal

from itertools import cycle

import numpy as np

import matplotlib.pyplot as plt
from matplotlib.widgets import Cursor

from hexrd.ui.constants import ViewType
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.zoom_canvas import ZoomCanvas


class LinePickerDialog(QObject):

    # Emits the ring data that was selected
    finished = Signal(list)

    def __init__(self, canvas, parent):
        super(LinePickerDialog, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('line_picker_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.canvas = canvas
        self.ring_data = []
        self.linebuilder = None
        self.lines = []

        self.zoom_canvas = ZoomCanvas(canvas)
        self.zoom_canvas.tth_tol = self.ui.zoom_tth_width.value()
        self.zoom_canvas.eta_tol = self.ui.zoom_eta_width.value()
        self.ui.layout().insertWidget(1, self.zoom_canvas)

        prop_cycle = plt.rcParams['axes.prop_cycle']
        self.color_cycler = cycle(prop_cycle.by_key()['color'])

        self.move_dialog_to_left()

        self.setup_connections()

    def setup_connections(self):
        self.ui.accepted.connect(self.accepted)
        self.ui.rejected.connect(self.rejected)
        self.ui.zoom_tth_width.valueChanged.connect(self.zoom_width_changed)
        self.ui.zoom_eta_width.valueChanged.connect(self.zoom_width_changed)
        self.bp_id = self.canvas.mpl_connect('button_press_event',
                                             self.button_pressed)

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

        self.zoom_canvas.cleanup()
        self.zoom_canvas = None

        self.canvas.mpl_disconnect(self.bp_id)
        self.bp_id = None
        self.canvas.draw()

    def zoom_width_changed(self):
        self.zoom_canvas.tth_tol = self.ui.zoom_tth_width.value()
        self.zoom_canvas.eta_tol = self.ui.zoom_eta_width.value()
        self.zoom_canvas.render()

    def start(self):
        if self.canvas.mode != ViewType.polar:
            print('line picker only works in polar mode!')
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
