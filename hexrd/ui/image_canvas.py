import copy
import math

from PySide2.QtCore import QThreadPool

from matplotlib.backends.backend_qt5agg import FigureCanvas

from matplotlib.figure import Figure
import matplotlib.pyplot as plt

import numpy as np

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.calibration.cartesian_plot import cartesian_viewer
from hexrd.ui.calibration.polar_plot import polar_viewer
from hexrd.ui.calibration.raw_iviewer import raw_iviewer
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui import utils
import hexrd.ui.constants


class ImageCanvas(FigureCanvas):

    def __init__(self, parent=None, image_names=None):
        self.figure = Figure()
        super(ImageCanvas, self).__init__(self.figure)

        self.raw_axes = []  # only used for raw currently
        self.axes_images = []
        self.overlay_artists = []
        self.cached_detector_borders = []
        self.saturation_texts = []
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.norm = None
        # The presence of an iviewer indicates we are currently viewing
        # a calibration.
        self.iviewer = None
        self.azimuthal_integral_axis = None
        self.azimuthal_line_artist = None

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
        HexrdConfig().overlay_config_changed.connect(self.update_overlays)
        HexrdConfig().show_saturation_level_changed.connect(
            self.show_saturation)
        HexrdConfig().detector_transform_modified.connect(
            self.on_detector_transform_modified)
        HexrdConfig().rerender_detector_borders.connect(
            self.draw_detector_borders)
        HexrdConfig().beam_vector_changed.connect(self.beam_vector_changed)

    def __del__(self):
        # This is so that the figure can be cleaned up
        plt.close(self.figure)

    def clear(self):
        self.iviewer = None
        self.figure.clear()
        self.raw_axes.clear()
        self.axes_images.clear()
        self.clear_overlays()
        self.azimuthal_integral_axis = None
        self.azimuthal_line_artist = None
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
                self.raw_axes.append(axis)

            self.figure.tight_layout()
        else:
            idx = HexrdConfig().current_imageseries_idx
            for i, name in enumerate(image_names):
                img = HexrdConfig().image(name, idx)
                self.axes_images[i].set_data(img)

        # This will call self.draw()
        self.show_saturation()

        # This will be used for drawing the rings
        self.iviewer = raw_iviewer()
        # Set the detectors to draw
        self.iviewer.detectors = [x.get_title() for x in self.raw_axes]
        self.update_overlays()

        msg = 'Image view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    def clear_overlays(self):
        while self.overlay_artists:
            self.overlay_artists.pop(0).remove()

    def overlay_axes_data(self, overlay):
        # Return the axes and data for drawing the overlay
        if not overlay['data']:
            return []

        if self.mode in ['cartesian', 'polar']:
            # If it's cartesian or polar, there is only one axis
            # Use the same axis for all of the data
            return [(self.axis, x) for x in overlay['data'].values()]

        # If it's raw, there is data for each axis.
        # The title of each axis should match the data key.
        return [(x, overlay['data'][x.get_title()]) for x in self.raw_axes]

    def overlay_draw_func(self, type):
        overlay_funcs = {
            'powder': self.draw_powder_overlay,
            'laue': self.draw_laue_overlay,
            'mono_rotation_series': self.draw_mono_rotation_series_overlay
        }

        if type not in overlay_funcs:
            raise Exception(f'Unknown overlay type: {type}')

        return overlay_funcs[type]

    def draw_overlay(self, overlay):
        type = overlay['type']
        style = overlay['style']
        for axis, data in self.overlay_axes_data(overlay):
            self.overlay_draw_func(type)(axis, data, style)

    def draw_powder_overlay(self, axis, data, style):
        rings = data['rings']
        rbnds = data['rbnds']
        rbnd_indices = data['rbnd_indices']

        data_style = style['data']
        ranges_style = style['ranges']

        for pr in rings:
            x, y = self.extract_ring_coords(pr)
            artist, = axis.plot(x, y, **data_style)
            self.overlay_artists.append(artist)

        # Add the rbnds too
        for ind, pr in zip(rbnd_indices, rbnds):
            x, y = self.extract_ring_coords(pr)
            current_style = copy.deepcopy(ranges_style)
            if len(ind) > 1:
                # If ranges are combined, override the color to red
                current_style['c'] = 'r'
            artist, = axis.plot(x, y, **current_style)
            self.overlay_artists.append(artist)

        if self.azimuthal_integral_axis is not None:
            az_axis = self.azimuthal_integral_axis
            for pr in rings:
                x, _ = self.extract_ring_coords(pr)
                # Don't plot duplicate vertical lines
                x = np.unique(x.round(3))
                for val in x:
                    ring = az_axis.axvline(val, **data_style)
                    self.overlay_artists.append(ring)

            # Add the rbnds too
            for ind, pr in zip(rbnd_indices, rbnds):
                x, _ = self.extract_ring_coords(pr)
                # Don't plot duplicate vertical lines
                x = np.unique(x.round(3))

                current_style = copy.deepcopy(ranges_style)
                if len(ind) > 1:
                    # If rbnds are combined, override the color to red
                    current_style['c'] = 'r'

                for val in x:
                    artist = az_axis.axvline(val, **current_style)
                    self.overlay_artists.append(artist)

    def draw_laue_overlay(self, axis, data, style):
        spots = data['spots']
        ranges = data['ranges']

        data_style = style['data']
        ranges_style = style['ranges']

        for x, y in spots:
            artist = axis.scatter(x, y, **data_style)
            self.overlay_artists.append(artist)

        for range in ranges:
            x, y = zip(*range)
            artist, = axis.plot(x, y, **ranges_style)
            self.overlay_artists.append(artist)

    def draw_mono_rotation_series_overlay(self, axis, data, style):
        pass

    def update_overlays(self):
        # iviewer is required for drawing rings
        if not self.iviewer:
            return

        self.clear_overlays()
        self.iviewer.update_overlay_data()

        for overlay in HexrdConfig().overlays:
            self.draw_overlay(overlay)

        self.draw()

    def clear_detector_borders(self):
        while self.cached_detector_borders:
            self.cached_detector_borders.pop(0).remove()

    def draw_detector_borders(self):
        self.clear_detector_borders()

        # If there is no iviewer, we are not currently viewing a
        # calibration. Just return.
        if not self.iviewer:
            self.draw()
            return

        # Make sure this is allowed by the configuration
        if not HexrdConfig().show_detector_borders:
            self.draw()
            return

        borders = self.iviewer.all_detector_borders
        for border in borders.values():
            # Draw each line in the border
            for line in border:
                plot, = self.axis.plot(*line, color='y', lw=2)
                self.cached_detector_borders.append(plot)

        self.draw()

    def extract_ring_coords(self, data):
        if self.mode == 'cartesian':
            # These are in x, y coordinates. Do not swap them.
            return data[:, 0], data[:, 1]

        return data[:, 1], data[:, 0]

    def clear_saturation(self):
        for t in self.saturation_texts:
            t.remove()
        self.saturation_texts.clear()
        self.draw()

    def show_saturation(self):
        self.clear_saturation()

        # Do not proceed without config approval
        if not HexrdConfig().show_saturation_level:
            return

        if not self.axes_images:
            return

        # Do not show the saturation in calibration mode
        if self.mode == 'cartesian' or self.mode == 'polar':
            return

        for img in self.axes_images:
            # The titles of the images are currently the detector names
            # If we change this in the future, we will need to change
            # our method for getting the saturation level as well.
            ax = img.axes
            detector_name = ax.get_title()
            detector = HexrdConfig().detector(detector_name)
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

    def beam_vector_changed(self):
        if not self.iviewer or not hasattr(self.iviewer, 'instr'):
            return

        bvec = HexrdConfig().instrument_config['beam']['vector']
        self.iviewer.instr.beam_vector = (bvec['azimuth'], bvec['polar_angle'])
        self.update_overlays()

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
        rescale_image = True
        if len(self.axes_images) == 0:
            self.axis = self.figure.add_subplot(111)
            self.axes_images.append(self.axis.imshow(img, cmap=self.cmap,
                                                     norm=self.norm,
                                                     vmin=None, vmax=None,
                                                     interpolation="none"))
            self.axis.set_xlabel(r'x (mm)')
            self.axis.set_ylabel(r'y (mm)')
        else:
            rescale_image = False
            self.axes_images[0].set_data(img)

        # We must adjust the extent of the image
        if rescale_image:
            self.axes_images[0].set_extent(iviewer.extent)
            self.axis.relim()
            self.axis.autoscale_view()
            self.axis.autoscale(False)
            self.figure.tight_layout()

        self.update_overlays()
        self.draw_detector_borders()

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

        rescale_image = True
        # TODO: maybe make this an option in the UI? Perhaps a checkbox
        # in the "View" menu?
        # if HexrdConfig().polar_show_azimuthal_integral
        if True:
            # The top image will have 2x the height of the bottom image
            grid = plt.GridSpec(3, 1)

            # It is important to persist the plot so that we don't reset the
            # scale.
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
                self.azimuthal_line_artist, = axis.plot(tth,
                                                        np.sum(img, axis=0))

                # Let the axes rescale one time
                axis.autoscale_view()

                # Turn off autoscale so modifying the rings does not
                # rescale the y axis.
                axis.autoscale(False)

                self.axis.set_ylabel(r'$\eta$ (deg)')

                self.azimuthal_integral_axis = axis
            else:
                self.update_azimuthal_integral_plot()
                axis = self.azimuthal_integral_axis

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

        self.update_overlays()
        self.draw_detector_borders()

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

    def update_azimuthal_integral_plot(self):
        if self.mode != 'polar':
            # Nothing to do. Just return.
            return

        axis = self.azimuthal_integral_axis
        line = self.azimuthal_line_artist
        if any([x is None for x in [axis, line]]):
            # Nothing to do. Just return.
            return

        # Get the "tth" vector
        tth = np.degrees(self.iviewer.angular_grid[1][0])

        # Set the new data
        line.set_data(tth, np.sum(self.iviewer.img, axis=0))

        # Rescale the axes for the new data
        # All three of these are required
        axis.relim()
        axis.autoscale_view()
        axis.axis('auto')

    def on_detector_transform_modified(self, det):
        if self.mode not in ['cartesian', 'polar']:
            return

        self.iviewer.update_detector(det)
        self.axes_images[0].set_data(self.iviewer.img)

        # This will only run if we are in polar mode
        self.update_azimuthal_integral_plot()

        # Update the detector borders if we are showing them
        # This will call self.draw()
        self.draw_detector_borders()

    def export_polar_plot(self, filename):
        if self.mode != 'polar':
            raise Exception('Not in polar mode. Cannot export polar plot')

        if not self.iviewer:
            raise Exception('No iviewer. Cannot export polar plot')

        self.iviewer.write_image(filename)

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

        if self.iviewer.snip1d_background is not None:
            background = self.iviewer.snip1d_background
        else:
            # We have to run it ourselves...
            # It should not have already been applied to the image
            background = utils.run_snip1d(self.iviewer.img)

        im = ax.imshow(background)

        im.set_extent(extent)
        ax.relim()
        ax.autoscale_view()
        ax.axis('auto')
        fig.tight_layout()

        fig.canvas.draw()
        fig.show()
