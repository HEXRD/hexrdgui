from PySide2.QtWidgets import QSizePolicy

from matplotlib.backends.backend_qt5agg import FigureCanvas

from matplotlib.figure import Figure

import numpy as np


class ZoomCanvas(FigureCanvas):

    def __init__(self, main_canvas, draw_crosshairs=True):
        self.figure = Figure()
        super().__init__(self.figure)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.main_canvas = main_canvas
        self.pv = main_canvas.iviewer.pv

        self.draw_crosshairs = draw_crosshairs

        self.axes_images = None

        # Set up the box overlay lines
        ax = self.main_canvas.axis
        self.box_overlay_line = ax.plot([], [], 'm-')[0]
        self.crosshairs = None

        # user-specified ROI in degrees (from interactors)
        self.tth_tol = 0.5
        self.eta_tol = 10.0

        self.setup_connections()

    def setup_connections(self):
        self.mne_id = self.main_canvas.mpl_connect('motion_notify_event',
                                                   self.mouse_moved)

    def __del__(self):
        self.cleanup()

    def cleanup(self):
        self.disconnect()
        self.remove_overlay_lines()

    def disconnect(self):
        if self.mne_id is not None:
            self.main_canvas.mpl_disconnect(self.mne_id)
            self.mne_id = None

    def remove_overlay_lines(self):
        if self.box_overlay_line is not None:
            self.box_overlay_line.remove()
            self.box_overlay_line = None

    def clear_crosshairs(self):
        if self.crosshairs is not None:
            self.crosshairs.set_data([], [])

    def remove_crosshairs(self):
        if self.crosshairs is not None:
            self.crosshairs.remove()
            self.crosshairs = None

    def mouse_moved(self, event):
        if event.inaxes is None:
            # Do nothing...
            return

        if not event.inaxes.get_images():
            # Image is over intensity plot. Do nothing...
            return

        self.xdata = event.xdata
        self.ydata = event.ydata

        self.render()

    def plot_crosshairs(self, xlims, ylims):
        x_scale = 0.05
        y_scale = 0.1

        center = np.array([np.mean(xlims), np.mean(ylims)])

        xmag = abs(xlims[1] - xlims[0]) * x_scale
        ymag = abs(ylims[1] - ylims[0]) * y_scale

        vals = [
            center + (0, ymag),
            center - (0, ymag),
            (np.nan, np.nan),
            center + (xmag, 0),
            center - (xmag, 0)
        ]

        self.crosshairs.set_data(zip(*vals))

    def render(self):
        self.clear_crosshairs()

        point = (self.xdata, self.ydata)
        rsimg = self.main_canvas.iviewer.img
        _extent = self.main_canvas.iviewer._extent
        pv = self.pv

        roi_diff = (np.tile([self.tth_tol, self.eta_tol], (4, 1)) * 0.5 *
                    np.vstack([[-1, -1], [1, -1], [1, 1], [-1, 1]]))
        roi_deg = np.tile(point, (4, 1)) + roi_diff

        # Clip the values into the required boundaries
        roi_deg[:, 0] = np.clip(roi_deg[:, 0],
                                *np.degrees((pv.tth_min, pv.tth_max)))
        roi_deg[:, 1] = np.clip(roi_deg[:, 1],
                                *np.degrees((pv.eta_min, pv.eta_max)))

        # get pixel values from PolarView class
        i_row = pv.eta_to_pixel(np.radians(roi_deg[:, 1]))
        j_col = pv.tth_to_pixel(np.radians(roi_deg[:, 0]))

        # Convert to intgers
        i_row = np.round(i_row).astype(int)
        j_col = np.round(j_col).astype(int)

        # plot
        roi = rsimg[i_row[1]:i_row[2], j_col[0]:j_col[1]]
        a2_data = (
            np.degrees(pv.angular_grid[1][0, j_col[0]:j_col[1]]),
            np.sum(roi, axis=0)
        )

        xlims = roi_deg[0:2, 0]
        ylims = roi_deg[2:0:-1, 1]

        if self.axes_images is None:
            grid = self.figure.add_gridspec(3, 1)
            a1 = self.figure.add_subplot(grid[:2, 0])
            a2 = self.figure.add_subplot(grid[2, 0], sharex=a1)
            a1.set_xlim(*xlims)
            a1.set_ylim(*ylims)
            im1 = a1.imshow(rsimg, extent=_extent, cmap=self.main_canvas.cmap,
                            norm=self.main_canvas.norm, picker=True,
                            interpolation='none')
            a1.axis('auto')
            a1.label_outer()
            im2, = a2.plot(a2_data[0], a2_data[1])
            self.figure.suptitle(r"ROI zoom")
            a2.set_xlabel(r"$2\theta$ [deg]")
            a2.set_ylabel(r"intensity")
            a1.set_ylabel(r"$\eta$ [deg]")
            self.crosshairs = a1.plot([], [], 'r-')[0]
            self.axes = [a1, a2]
            self.axes_images = [im1, im2]
            self.grid = grid
        else:
            self.axes[0].set_xlim(*xlims)
            self.axes[0].set_ylim(*ylims)
            self.axes_images[1].set_data(a2_data)

            self.axes[1].relim()
            self.axes[1].autoscale_view(scalex=False)

        if self.draw_crosshairs:
            self.plot_crosshairs(xlims, ylims)

        xs = np.append(roi_deg[:, 0], roi_deg[0, 0])
        ys = np.append(roi_deg[:, 1], roi_deg[0, 1])
        self.box_overlay_line.set_data(xs, ys)

        self.main_canvas.draw()
        self.draw()
