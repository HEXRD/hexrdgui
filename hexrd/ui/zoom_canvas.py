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

    def clear(self):
        self.figure.clear()

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
        self.clear()

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
        grid = plt.GridSpec(3, 1)
        a1 = self.figure.add_subplot(grid[:2, 0])
        a2 = self.figure.add_subplot(grid[2, 0], sharex=a1)
        a1.imshow(roi, extent=extent)
        a1.axis('auto')
        a2.plot(
            np.degrees(
                pv.angular_grid[1][0, cc.reshape(len(np.unique(rr)),
                                                 len(np.unique(cc)))[0, :]]
            ),
            np.sum(roi, axis=0)
        )
        self.figure.suptitle(r"ROI zoom")
        a2.set_xlabel(r"$2\theta$ [deg]")
        a2.set_ylabel(r"intensity")
        a1.set_ylabel(r"$\eta$ [deg]")

        self.box_overlay_lines[0].set_data(roi_deg[:, 0], roi_deg[:, 1])
        self.box_overlay_lines[1].set_data(roi_deg[[-1, 0], 0], roi_deg[[-1, 0], 1])

        self.main_canvas.draw()
        self.draw()
