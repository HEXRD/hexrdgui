import copy
import math

from PySide2.QtCore import QThreadPool

from matplotlib.backends.backend_qt5agg import FigureCanvas

from matplotlib.figure import Figure
import matplotlib.pyplot as plt

import numpy as np

from skimage.filters.edges import binary_erosion
from skimage.morphology import disk

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.calibration.cartesian_plot import cartesian_viewer
from hexrd.ui.calibration.polar_plot import polar_viewer
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.utils import run_snip1d, snip_width_pixels
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
        self.cartesian_res_config = (
            HexrdConfig().config['image']['cartesian'].copy()
        )
        self.polar_res_config = HexrdConfig().config['image']['polar'].copy()

        # Set up our async stuff
        self.thread_pool = QThreadPool(parent)

        if image_names is not None:
            self.load_images(image_names)

        self.setup_connections()

    def setup_connections(self):
        HexrdConfig().ring_config_changed.connect(self.redraw_rings)
        HexrdConfig().show_saturation_level_changed.connect(
            self.show_saturation)
        HexrdConfig().detector_transform_modified.connect(
            self.on_detector_transform_modified)

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
        HexrdConfig().emit_update_status_bar('Loading image view...')
        if self.mode != 'images' or len(image_names) != len(self.axes_images):
            # Either we weren't in image mode before, or we have a different
            # number of images. Clear and re-draw.
            self.clear()
            self.mode = 'images'

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
        else:
            idx = HexrdConfig().current_imageseries_idx
            for i, name in enumerate(image_names):
                img = HexrdConfig().image(name, idx)
                self.axes_images[i].set_data(img)

        # This will call self.draw()
        self.show_saturation()

        msg = 'Image view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

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
        HexrdConfig().emit_update_status_bar('Loading Cartesian view...')
        if self.mode != 'cartesian':
            self.clear()
            self.mode = 'cartesian'

        # Force a redraw when the pixel size changes.
        if (self.cartesian_res_config !=
                HexrdConfig().config['image']['cartesian']):
            self.cartesian_res_config = (
                HexrdConfig().config['image']['cartesian'].copy()
            )
            self.figure.clear()
            self.axes_images.clear()

        # Run the calibration in a background thread
        worker = AsyncWorker(cartesian_viewer)
        self.thread_pool.start(worker)

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_show_cartesian)

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

        msg = 'Cartesian view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    def show_polar(self):
        HexrdConfig().emit_update_status_bar('Loading polar view...')
        if self.mode != 'polar':
            self.clear()
            self.mode = 'polar'

        polar_res_config = HexrdConfig().config['image']['polar']
        if self._polar_reset_needed(polar_res_config):
            # Reset the whole image when certain config items change
            self.clear()
            self.mode = 'polar'

        self.polar_res_config = polar_res_config.copy()

        # Run the calibration in a background thread
        worker = AsyncWorker(polar_viewer)
        self.thread_pool.start(worker)

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_show_polar)

    def finish_show_polar(self, iviewer):
        self.iviewer = iviewer
        img = self.iviewer.img
        extent = self.iviewer._extent

        if HexrdConfig().polar_apply_snip1d:
            # Make a deep copy of the image to edit
            img = copy.deepcopy(img)

            background = run_snip1d(img)
            # Perform the background subtraction
            img -= background

            if HexrdConfig().polar_apply_erosion:
                erosion_element = disk(2 * snip_width_pixels())
                threshold = self.norm.vmin

                mask = binary_erosion(img > threshold, structure=erosion_element)
                img[~mask] = 0

        rescale_image = True
        # TODO: maybe make this an option in the UI? Perhaps a checkbox
        # in the "View" menu?
        # if HexrdConfig().polar_show_azimuthal_integral
        if True:
            # The top image will have 2x the height of the bottom image
            grid = plt.GridSpec(3, 1)

            # It is important to persist the plot so that we don't reset the scale.
            if len(self.axes_images) == 0:
                self.axis = self.figure.add_subplot(grid[:2, 0])
                self.axes_images.append(self.axis.imshow(img, cmap=self.cmap,
                                                         norm=self.norm,
                                                         picker=True,
                                                         interpolation='none'))
            else:
                rescale_image = False
                self.axes_images[0].set_data(img)

            # Get the "tth" vector
            angular_grid = self.iviewer.angular_grid
            tth = np.degrees(angular_grid[1][0])

            if self.azimuthal_integral_axis is None:
                axis = self.figure.add_subplot(grid[2, 0], sharex=self.axis)
                axis.plot(tth, np.sum(img, axis=0))

                # Turn off autoscale so modifying the rings does not
                # rescale the y axis.
                axis.autoscale(False)

                self.axis.set_ylabel(r'$\eta$ (deg)')

                self.azimuthal_integral_axis = axis
            else:
                axis = self.azimuthal_integral_axis
                axis.clear()
                axis.plot(tth, np.sum(img, axis=0))

            # These need to be set every time for some reason
            self.axis.label_outer()
            axis.set_xlabel(r'2$\theta$ (deg)')
            axis.set_ylabel(r'Azimuthal Integration')

            # If the x limits are outside what the user set,
            # modify them.
            x_min = HexrdConfig().polar_res_tth_min
            x_max = HexrdConfig().polar_res_tth_max
            xlim = axis.get_xlim()
            if xlim[0] < x_min:
                axis.set_xlim(left=x_min)
            if xlim[1] > x_max:
                axis.set_xlim(right=x_max)
        else:
            if len(self.axes_images) == 0:
                self.axis = self.figure.add_subplot(111)
                self.axes_images.append(self.axis.imshow(img, cmap=self.cmap,
                                                         norm=self.norm,
                                                         picker=True,
                                                         interpolation='none'))
                self.axis.set_xlabel(r'2$\theta$ (deg)')
                self.axis.set_ylabel(r'$\eta$ (deg)')
            else:
                rescale_image = False
                self.axes_images[0].set_data(img)

        # We must adjust the extent of the image
        if rescale_image:
            self.axes_images[0].set_extent(extent)
            self.axis.relim()
            self.axis.autoscale_view()
            self.axis.axis('auto')
            self.figure.tight_layout()

        self.redraw_rings()

        msg = 'Polar view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

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

    def on_detector_transform_modified(self, det):
        if not self.iviewer:
            return

        self.iviewer.update_detector(det)
        self.axes_images[0].set_data(self.iviewer.img)
        self.draw()

    def _polar_reset_needed(self, new_polar_config):
        # If any of the entries on this list were changed, a reset is needed
        reset_needed_list = [
            'pixel_size_tth',
            'pixel_size_eta',
            'tth_min',
            'tth_max'
        ]

        for key in reset_needed_list:
            if self.polar_res_config[key] != new_polar_config[key]:
                return True

        return False

    def polar_show_snip1d(self):
        if self.mode != 'polar':
            print('snip1d may only be shown in polar mode!')
            return

        if self.iviewer is None:
            print('No instrument viewer! Cannot generate snip1d!')
            return

        if self.iviewer.img is None:
            print('No image! Cannot generate snip1d!')

        img = self.iviewer.img
        extent = self.iviewer._extent

        if not hasattr(self, '_snip1d_figure_cache'):
            # Create the figure and axes to use
            fig, ax = plt.subplots()
            ax.set_title('snip1d')
            ax.set_xlabel(r'2$\theta$ (deg)')
            ax.set_ylabel(r'$\eta$ (deg)')
            fig.canvas.set_window_title('HEXRD')
            self._snip1d_figure_cache = (fig, ax)
        else:
            fig, ax = self._snip1d_figure_cache

        background = run_snip1d(img)
        im = ax.imshow(background, cmap=self.cmap, norm=self.norm,
                       picker=True, interpolation='none')

        im.set_extent(extent)
        ax.relim()
        ax.autoscale_view()
        ax.axis('auto')
        fig.tight_layout()

        fig.canvas.draw()
        fig.show()
