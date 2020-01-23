from matplotlib.backends.backend_qt5agg import FigureCanvas

from matplotlib.figure import Figure
import matplotlib.pyplot as plt

from skimage.draw import polygon

import numpy as np


class ZoomCanvas(FigureCanvas):

    def __init__(self, main_canvas):
        self.figure = Figure()
        super(FigureCanvas, self).__init__(self.figure)

        self.main_canvas = main_canvas
        self.pv = main_canvas.iviewer.pv

        self.axes_images = None

        # Set up the box overlay lines
        ax = self.main_canvas.axis
        self.box_overlay_lines = []
        self.box_overlay_lines.append(ax.plot([], [], 'm-')[0])
        self.box_overlay_lines.append(ax.plot([], [], 'm-')[0])

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
        while self.box_overlay_lines:
            self.box_overlay_lines.pop(0).remove()

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

    def render(self):
        point = (self.xdata, self.ydata)
        rsimg = self.main_canvas.iviewer.img
        pv = self.pv

        tth_tol = self.tth_tol
        eta_tol = self.eta_tol

        roi_diff = (np.tile([tth_tol, eta_tol], (4, 1)) * 0.5 *
                    np.vstack([[-1, -1], [1, -1], [1, 1], [-1, 1]]))
        roi_deg = np.tile(point, (4, 1)) + roi_diff

        # get pixel values from PolarView class
        i_row = pv.eta_to_pixel(np.radians(roi_deg[:, 1]))
        j_col = pv.tth_to_pixel(np.radians(roi_deg[:, 0]))

        # file rectangle
        rr, cc = polygon(i_row, j_col, shape=rsimg.shape)
        eta_pix_cen = np.degrees(pv.angular_grid[0][rr, 0])
        tth_pix_cen = np.degrees(pv.angular_grid[1][0, cc])
        extent = [
            min(tth_pix_cen) - 0.5 * pv.tth_pixel_size,
            max(tth_pix_cen) + 0.5 * pv.tth_pixel_size,
            max(eta_pix_cen) + 0.5 * pv.eta_pixel_size,
            min(eta_pix_cen) - 0.5 * pv.eta_pixel_size
        ]

        # roi
        roi = rsimg[rr, cc].reshape(len(np.unique(rr)), len(np.unique(cc)))

        # plot
        a2_data = (
            np.degrees(
                pv.angular_grid[1][0, cc.reshape(len(np.unique(rr)),
                                                 len(np.unique(cc)))[0, :]]
            ),
            np.sum(roi, axis=0)
        )
        if self.axes_images is None:
            grid = self.figure.add_gridspec(3, 1)
            a1 = self.figure.add_subplot(grid[:2, 0])
            a2 = self.figure.add_subplot(grid[2, 0], sharex=a1)
            im1 = a1.imshow(roi, extent=extent, cmap=self.main_canvas.cmap,
                            norm=self.main_canvas.norm, picker=True,
                            interpolation='none')
            a1.axis('auto')
            a1.label_outer()
            im2 = a2.plot(a2_data)[0]
            self.figure.suptitle(r"ROI zoom")
            a2.set_xlabel(r"$2\theta$ [deg]")
            a2.set_ylabel(r"intensity")
            a1.set_ylabel(r"$\eta$ [deg]")
            self.axes = [a1, a2]
            self.axes_images = [im1, im2]
            self.grid = grid
        else:
            self.axes_images[0].set_data(roi)
            self.axes_images[0].set_extent(extent)
            self.axes_images[1].set_data(a2_data)

            # I can't figure out how to get the bottom axis to autoscale
            # properly. Do it manually.
            data_min, data_max = a2_data[1].min(), a2_data[1].max()
            ymin = data_min - 0.1 * (data_max - data_min) - 1.e-6
            ymax = data_max + 0.1 * (data_max - data_min) + 1.e-6
            self.axes[1].set_ylim((ymin, ymax))

        self.box_overlay_lines[0].set_data(roi_deg[:, 0], roi_deg[:, 1])
        self.box_overlay_lines[1].set_data(roi_deg[[-1, 0], 0], roi_deg[[-1, 0], 1])

        self.main_canvas.draw()
        self.draw()
