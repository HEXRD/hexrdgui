import math

from PySide2.QtCore import QThreadPool

from matplotlib.backends.backend_qt5agg import FigureCanvas

from matplotlib.figure import Figure
import matplotlib.pyplot as plt

import numpy as np

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.cal_progress_dialog import CalProgressDialog
from hexrd.ui.calibration.cartesian_plot import cartesian_viewer
from hexrd.ui.calibration.polar_plot import polar_viewer
from hexrd.ui.hexrd_config import HexrdConfig
import hexrd.ui.constants


class ImageCanvas(FigureCanvas):

    def __init__(self, parent=None, image_names=None):
        self.figure = Figure()
        super(ImageCanvas, self).__init__(self.figure)

        self.axes_images = []
        self.cached_rings = []
        self.cached_rbnds = []
        self.saturation_texts = []
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.norm = None
        # The presence of an iviewer indicates we are currently viewing
        # a calibration.
        self.iviewer = None
        self.azimuthal_integral_axis = None

        # Track the current mode so that we can more lazily clear on change.
        self.mode = None

        # Track the pixel size
        self.cartesian_pixel_size = HexrdConfig().cartesian_pixel_size

        # Set up our async stuff
        self.thread_pool = QThreadPool(parent)
        self.cal_progress_dialog = CalProgressDialog(parent)

        if image_names is not None:
            self.load_images(image_names)

        self.setup_connections()

    def setup_connections(self):
        HexrdConfig().ring_config_changed.connect(self.redraw_rings)
        HexrdConfig().show_saturation_level_changed.connect(
            self.show_saturation)

    def __del__(self):
        # This is so that the figure can be cleaned up
        plt.close(self.figure)

    def clear(self):
        self.iviewer = None
        self.figure.clear()
        self.axes_images.clear()
        self.clear_rings()
        self.azimuthal_integral_axis = None
        self.mode = None

    def load_images(self, image_names):
        # TODO: Make this lazily clear only if number of images changes.
        if self.mode != 'images':
            self.clear()
            self.mode = 'images'

        self.clear()

        cols = 1
        if len(image_names) > 1:
            cols = 2

        rows = math.ceil(len(image_names) / cols)

        idx = HexrdConfig().current_imageseries_idx
        for i, name in enumerate(image_names):
            img = HexrdConfig().image(name, idx)

            axis = self.figure.add_subplot(rows, cols, i + 1)
            axis.set_title(name)
            self.axes_images.append(axis.imshow(img, cmap=self.cmap,
                                                norm=self.norm))

        self.figure.tight_layout()

        # This will call self.draw()
        self.show_saturation()

    def clear_rings(self):
        while self.cached_rings:
            self.cached_rings.pop(0).remove()

        while self.cached_rbnds:
            self.cached_rbnds.pop(0).remove()

    def redraw_rings(self):
        # If there is no iviewer, we are not currently viewing a
        # calibration. Just return.
        if not self.iviewer:
            return

        self.clear_rings()

        # In case the plane data has changed
        self.iviewer.plane_data = HexrdConfig().active_material.planeData

        ring_data = self.iviewer.add_rings()

        colorspec = 'c.'
        if self.iviewer.type == 'polar':
            colorspec = 'c.-'

        for pr in ring_data:
            ring, = self.axis.plot(pr[:, 1], pr[:, 0], colorspec, ms=2)
            self.cached_rings.append(ring)

        # Add the rbnds too
        for ind, pr in zip(self.iviewer.rbnd_indices,
                           self.iviewer.rbnd_data):
            color = 'g:'
            if len(ind) > 1:
                color = 'r:'
            rbnd, = self.axis.plot(pr[:, 1], pr[:, 0], color, ms=1)
            self.cached_rbnds.append(rbnd)

        if self.azimuthal_integral_axis is not None:
            axis = self.azimuthal_integral_axis
            yrange = axis.get_ylim()
            for pr in ring_data:
                ring, = axis.plot(pr[:, 1], yrange, colorspec, ms=2)
                self.cached_rings.append(ring)

            # Add the rbnds too
            for ind, pr in zip(self.iviewer.rbnd_indices,
                               self.iviewer.rbnd_data):
                color = 'g:'
                if len(ind) > 1:
                    color = 'r:'
                rbnd, = axis.plot(pr[:, 1], yrange, color, ms=1)
                self.cached_rbnds.append(rbnd)

        self.draw()

    def clear_saturation(self):
        for t in self.saturation_texts:
            t.remove()
        self.saturation_texts.clear()
        self.draw()

    def show_saturation(self):
        # Do not proceed without config approval
        if not HexrdConfig().show_saturation_level:
            self.clear_saturation()
            return

        if not self.axes_images:
            self.clear_saturation()
            return

        # Do not show the saturation in calibration mode
        if self.mode == 'cartesian' or self.mode == 'polar':
            self.clear_saturation()
            return

        for img in self.axes_images:
            # The titles of the images are currently the detector names
            # If we change this in the future, we will need to change
            # our method for getting the saturation level as well.
            ax = img.axes
            detector_name = ax.get_title()
            detector = HexrdConfig().get_detector(detector_name)
            saturation_level = detector['saturation_level']['value']

            array = img.get_array()

            num_sat = (array >= saturation_level).sum()
            percent = num_sat / array.size * 100.0
            str_sat = 'Saturation: ' + str(num_sat)
            str_sat += '\n%5.3f %%' % percent

            t = ax.text(0.05, 0.05, str_sat, fontdict={'color': 'w'},
                        transform=ax.transAxes)
            self.saturation_texts.append(t)

        self.draw()

    def show_cartesian(self):
        if self.mode != 'cartesian':
            self.clear()
            self.mode = 'cartesian'

        # Force a redraw when the pixel size changes.
        if self.cartesian_pixel_size != HexrdConfig().cartesian_pixel_size:
            self.cartesian_pixel_size = HexrdConfig().cartesian_pixel_size
            self.figure.clear()
            self.axes_images.clear()

        if self.iviewer is None:
            self.figure.clear()
            self.axes_images.clear()

        # Run the calibration in a background thread
        worker = AsyncWorker(cartesian_viewer)
        self.thread_pool.start(worker)

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_show_cartesian)
        worker.signals.finished.connect(self.cal_progress_dialog.accept)
        #self.cal_progress_dialog.exec_()

    def finish_show_cartesian(self, iviewer):
        self.iviewer = iviewer
        img = self.iviewer.img

        # It is important to persist the plot so that we don't reset the scale.
        if len(self.axes_images) == 0:
            self.axis = self.figure.add_subplot(111)
            self.axes_images.append(self.axis.imshow(img, cmap=self.cmap,
                                                     norm=self.norm,
                                                     vmin = None, vmax = None,
                                                     interpolation = "none"))
        else:
            self.axes_images[0].set_data(img)

        self.redraw_rings()

    def show_polar(self):
        # TODO: Make this set updated data on updates, not clear/redraw.
        if self.mode != 'polar':
            self.clear()
            self.mode = 'polar'
        self.clear()

        # Run the calibration in a background thread
        worker = AsyncWorker(polar_viewer)
        self.thread_pool.start(worker)

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_show_polar)
        worker.signals.finished.connect(self.cal_progress_dialog.accept)
        self.cal_progress_dialog.exec_()

    def finish_show_polar(self, iviewer):
        self.iviewer = iviewer
        img = self.iviewer.img
        extent = self.iviewer._extent

        # TODO: maybe make this an option in the UI? Perhaps a checkbox
        # in the "View" menu?
        # if HexrdConfig().polar_show_azimuthal_integral
        if True:
            # The top image will have 2x the height of the bottom image
            grid = plt.GridSpec(3, 1)
            self.axis = self.figure.add_subplot(grid[:2, 0])
            self.axes_images.append(self.axis.imshow(img, cmap=self.cmap,
                                                     norm=self.norm,
                                                     picker=True,
                                                     interpolation='none'))

            # Get the "tth" vector
            angular_grid = self.iviewer.angular_grid
            tth = np.degrees(angular_grid[1][0])

            self.axis.set_ylabel(r'$\eta$ (deg)')

            axis = self.figure.add_subplot(grid[2, 0], sharex=self.axis)
            axis.plot(tth, np.sum(img, axis=0))

            self.axis.label_outer()
            axis.set_xlabel(r'2$\theta$ (deg)')
            axis.set_ylabel(r'Azimuthal Integration')

            x_min = HexrdConfig().polar_res_tth_min
            x_max = HexrdConfig().polar_res_tth_max
            axis.set_xlim(x_min, x_max)

            self.azimuthal_integral_axis = axis
        else:
            self.axis = self.figure.add_subplot(111)
            self.axes_images.append(self.axis.imshow(img, cmap=self.cmap,
                                                     norm=self.norm,
                                                     picker=True,
                                                     interpolation='none'))
            self.axis.set_xlabel(r'2$\theta$ (deg)')
            self.axis.set_ylabel(r'$\eta$ (deg)')

        # We must adjust the extent of the image
        self.axes_images[0].set_extent(extent)
        self.axis.relim()
        self.axis.autoscale_view()
        self.axis.axis('auto')

        self.redraw_rings()

    def set_cmap(self, cmap):
        self.cmap = cmap
        for axes_image in self.axes_images:
            axes_image.set_cmap(cmap)
        self.draw()

    def set_norm(self, norm):
        self.norm = norm
        for axes_image in self.axes_images:
            axes_image.set_norm(norm)
        self.draw()

    def get_min_max(self):
        minimum = min([x.get_array().min() for x in self.axes_images])
        maximum = max([x.get_array().max() for x in self.axes_images])

        return minimum, maximum

    def percentile_range(self, low = 69.0, high = 99.9):
        l = min([np.percentile(x.get_array(), low) for x in self.axes_images])
        h = min([np.percentile(x.get_array(), high) for x in self.axes_images])

        if h - l < 5:
            h = l + 5

        # This debug is useful for now, keeping it in for sanity...
        print("Range to be used: ", l, " -> ", h)

        return l, h
