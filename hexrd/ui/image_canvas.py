import copy
import math

from PySide2.QtCore import QThreadPool, QTimer
from PySide2.QtWidgets import QMessageBox

from matplotlib.backends.backend_qt5agg import FigureCanvas

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

import numpy as np

from hexrd.transforms.xfcapi import mapAngle

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.calibration.cartesian_plot import cartesian_viewer
from hexrd.ui.calibration.polar_plot import polar_viewer
from hexrd.ui.calibration.raw_iviewer import raw_iviewer
from hexrd.ui.constants import OverlayType, ViewType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui import utils
import hexrd.ui.constants


class ImageCanvas(FigureCanvas):

    def __init__(self, parent=None, image_names=None):
        self.figure = Figure()
        super().__init__(self.figure)

        self.raw_axes = []  # only used for raw currently
        self.axes_images = []
        self.overlay_artists = {}
        self.cached_detector_borders = []
        self.saturation_texts = []
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.norm = None
        self.iviewer = None
        self.azimuthal_integral_axis = None
        self.azimuthal_line_artist = None
        self.wppf_plot = None
        self.auto_picked_data_artists = []

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
        HexrdConfig().rerender_wppf.connect(self.draw_wppf)
        HexrdConfig().rerender_auto_picked_data.connect(
            self.draw_auto_picked_data)
        HexrdConfig().beam_vector_changed.connect(self.beam_vector_changed)
        HexrdConfig().polar_masks_changed.connect(self.update_polar)

    def __del__(self):
        # This is so that the figure can be cleaned up
        plt.close(self.figure)

    def clear(self):
        self.iviewer = None
        self.mode = None
        self.clear_figure()

    def clear_figure(self):
        self.figure.clear()
        self.raw_axes.clear()
        self.axes_images.clear()
        self.remove_all_overlay_artists()
        self.clear_azimuthal_integral_axis()
        self.mode = None

    def clear_azimuthal_integral_axis(self):
        self.clear_wppf_plot()
        self.azimuthal_integral_axis = None
        self.azimuthal_line_artist = None
        HexrdConfig().last_azimuthal_integral_data = None

    def clear_wppf_plot(self):
        if self.wppf_plot:
            self.wppf_plot.remove()
            self.wppf_plot = None

    def clear_auto_picked_data_artists(self):
        while self.auto_picked_data_artists:
            self.auto_picked_data_artists.pop(0).remove()

    def load_images(self, image_names):
        HexrdConfig().emit_update_status_bar('Loading image view...')
        if (self.mode != ViewType.raw or
                len(image_names) != len(self.axes_images)):
            # Either we weren't in image mode before, we have a different
            # number of images, or there are masks to apply. Clear and re-draw.
            self.clear()
            self.mode = ViewType.raw

            # This will be used for drawing the rings
            self.iviewer = raw_iviewer()

            cols = 1
            if len(image_names) > 1:
                cols = 2

            rows = math.ceil(len(image_names) / cols)

            idx = HexrdConfig().current_imageseries_idx
            for i, name in enumerate(image_names):
                img = HexrdConfig().image(name, idx)

                if HexrdConfig().apply_pixel_solid_angle_correction:
                    panel = self.iviewer.instr.detectors[name]
                    img = img / panel.pixel_solid_angles

                # Apply any masks
                for mask_name, (det, mask) in HexrdConfig().raw_masks.items():
                    if (mask_name in HexrdConfig().visible_masks and
                            det == name):
                        img[~mask] = 0

                axis = self.figure.add_subplot(rows, cols, i + 1)
                axis.set_title(name)
                kwargs = {
                    'X': img,
                    'cmap': self.cmap,
                    'norm': self.norm,
                    'interpolation': 'none',
                }
                self.axes_images.append(axis.imshow(**kwargs))
                axis.autoscale(False)
                self.raw_axes.append(axis)

            self.figure.tight_layout()
        else:
            idx = HexrdConfig().current_imageseries_idx
            for i, name in enumerate(image_names):
                img = HexrdConfig().image(name, idx)
                # Apply any masks
                for mask_name, (det, mask) in HexrdConfig().raw_masks.items():
                    if (mask_name in HexrdConfig().visible_masks and
                            det == name):
                        img[~mask] = 0
                self.axes_images[i].set_data(img)

        # This will call self.draw_idle()
        self.show_saturation()

        # Set the detectors to draw
        self.iviewer.detectors = [x.get_title() for x in self.raw_axes]
        self.update_auto_picked_data()
        self.update_overlays()

        msg = 'Image view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    def remove_all_overlay_artists(self):
        while self.overlay_artists:
            key = next(iter(self.overlay_artists))
            self.remove_overlay_artists(key)

    def remove_overlay_artists(self, key):
        artists = self.overlay_artists[key]
        while artists:
            artists.pop(0).remove()
        del self.overlay_artists[key]

    def overlay_axes_data(self, overlay):
        # Return the axes and data for drawing the overlay
        if not overlay['data']:
            return []

        if self.mode in [ViewType.cartesian, ViewType.polar]:
            # If it's cartesian or polar, there is only one axis
            # Use the same axis for all of the data
            return [(self.axis, x) for x in overlay['data'].values()]

        # If it's raw, there is data for each axis.
        # The title of each axis should match the data key.
        return [(x, overlay['data'][x.get_title()]) for x in self.raw_axes]

    def overlay_draw_func(self, type):
        overlay_funcs = {
            OverlayType.powder: self.draw_powder_overlay,
            OverlayType.laue: self.draw_laue_overlay,
            OverlayType.mono_rotation_series: (
                self.draw_mono_rotation_series_overlay)
        }

        if type not in overlay_funcs:
            raise Exception(f'Unknown overlay type: {type}')

        return overlay_funcs[type]

    def get_overlay_highlight_ids(self, overlay):
        highlights = overlay.get('highlights')
        if not highlights:
            return []

        def recursive_get(cur, path):
            for p in path:
                cur = cur[p]
            return cur

        return [id(recursive_get(overlay['data'], h)) for h in highlights]

    def draw_overlay(self, overlay):
        if not overlay['visible']:
            return

        # Keep track of any overlays we need to highlight
        self.overlay_highlight_ids += self.get_overlay_highlight_ids(overlay)

        type = overlay['type']
        style = overlay['style']
        for axis, data in self.overlay_axes_data(overlay):
            if id(data) in self.overlay_artists:
                # It's already present. Skip it.
                continue

            self.overlay_draw_func(type)(axis, data, style)

    def draw_powder_overlay(self, axis, data, style):
        rings = data['rings']
        rbnds = data['rbnds']
        rbnd_indices = data['rbnd_indices']

        data_style = style['data']
        ranges_style = style['ranges']

        highlight_style = hexrd.ui.constants.HIGHLIGHT_POWDER_STYLE
        highlight_indices = [i for i, x in enumerate(rings)
                             if id(x) in self.overlay_highlight_ids]

        artists = []
        self.overlay_artists[id(data)] = artists
        for i, pr in enumerate(rings):
            current_style = data_style
            if i in highlight_indices:
                # Override with highlight style
                current_style = highlight_style['data']

            x, y = self.extract_ring_coords(pr)
            artist, = axis.plot(x, y, **current_style)
            artists.append(artist)

        # Add the rbnds too
        for ind, pr in zip(rbnd_indices, rbnds):
            x, y = self.extract_ring_coords(pr)
            current_style = copy.deepcopy(ranges_style)
            if any(x in highlight_indices for x in ind):
                # Override with highlight style
                current_style = highlight_style['ranges']
            elif len(ind) > 1:
                # If ranges are combined, override the color to red
                current_style['c'] = 'r'
            artist, = axis.plot(x, y, **current_style)
            artists.append(artist)

        if self.azimuthal_integral_axis is not None:
            az_axis = self.azimuthal_integral_axis
            for pr in rings:
                x, _ = self.extract_ring_coords(pr)
                # Average the points together for the vertical line
                x = np.nanmean(x)
                artist = az_axis.axvline(x, **data_style)
                artists.append(artist)

            # Add the rbnds too
            for ind, pr in zip(rbnd_indices, rbnds):
                x, _ = self.extract_ring_coords(pr)
                # Average the points together for the vertical line
                x = np.nanmean(x)

                current_style = copy.deepcopy(ranges_style)
                if len(ind) > 1:
                    # If rbnds are combined, override the color to red
                    current_style['c'] = 'r'

                artist = az_axis.axvline(x, **current_style)
                artists.append(artist)

    def draw_laue_overlay(self, axis, data, style):
        spots = data['spots']
        ranges = data['ranges']

        data_style = style['data']
        ranges_style = style['ranges']

        highlight_style = hexrd.ui.constants.HIGHLIGHT_LAUE_STYLE
        highlight_indices = [i for i, x in enumerate(spots)
                             if id(x) in self.overlay_highlight_ids]

        artists = []
        self.overlay_artists[id(data)] = artists
        for i, (x, y) in enumerate(spots):
            current_style = data_style
            if i in highlight_indices:
                current_style = highlight_style['data']

            artist = axis.scatter(x, y, **current_style)
            artists.append(artist)

        for i, box in enumerate(ranges):
            current_style = ranges_style
            if i in highlight_indices:
                current_style = highlight_style['ranges']

            x, y = zip(*box)
            artist, = axis.plot(x, y, **current_style)
            artists.append(artist)

    def draw_mono_rotation_series_overlay(self, id, axis, data, style):
        pass

    def update_overlays(self):
        # iviewer is required for drawing rings
        if not self.iviewer:
            return

        if not HexrdConfig().show_overlays:
            self.remove_all_overlay_artists()
            self.draw_idle()
            return

        def overlay_with_data_id(data_id):
            for overlay in HexrdConfig().overlays:
                if any([data_id == id(x) for x in overlay['data'].values()]):
                    return overlay

            return None

        # Remove any artists that:
        # 1. Are no longer in the list of overlays
        # 2. Are not visible
        # 3. Need updating
        for key in list(self.overlay_artists.keys()):
            overlay = overlay_with_data_id(key)
            if overlay is None:
                # This artist is no longer a part of the overlays
                self.remove_overlay_artists(key)
                continue

            if overlay.get('update_needed', True) or not overlay['visible']:
                self.remove_overlay_artists(key)
                continue

        self.iviewer.update_overlay_data()

        self.overlay_highlight_ids = []
        for overlay in HexrdConfig().overlays:
            self.draw_overlay(overlay)

        self.draw_idle()

    def clear_detector_borders(self):
        while self.cached_detector_borders:
            self.cached_detector_borders.pop(0).remove()

    def draw_detector_borders(self):
        self.clear_detector_borders()

        # If there is no iviewer, we are not currently viewing a
        # calibration. Just return.
        if not self.iviewer:
            self.draw_idle()
            return

        # Make sure this is allowed by the configuration
        if not HexrdConfig().show_detector_borders:
            self.draw_idle()
            return

        borders = self.iviewer.all_detector_borders
        for border in borders.values():
            # Draw each line in the border
            for line in border:
                plot, = self.axis.plot(*line, color='y', lw=2)
                self.cached_detector_borders.append(plot)

        self.draw_idle()

    def draw_wppf(self):
        self.update_wppf_plot()
        self.draw_idle()

    def draw_auto_picked_data(self):
        self.update_auto_picked_data()
        self.draw_idle()

    def extract_ring_coords(self, data):
        if self.mode == ViewType.cartesian:
            # These are in x, y coordinates. Do not swap them.
            return data[:, 0], data[:, 1]

        return data[:, 1], data[:, 0]

    def clear_saturation(self):
        for t in self.saturation_texts:
            t.remove()
        self.saturation_texts.clear()
        self.draw_idle()

    def show_saturation(self):
        self.clear_saturation()

        # Do not proceed without config approval
        if not HexrdConfig().show_saturation_level:
            return

        if not self.axes_images:
            return

        # Do not show the saturation in calibration mode
        if self.mode != ViewType.raw:
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

        self.draw_idle()

    def beam_vector_changed(self):
        if self.mode == ViewType.polar:
            # Polar needs a complete re-draw
            # Only emit this once every 100 milliseconds or so to avoid
            # too many updates if the slider widget is being used.
            if not hasattr(self, '_beam_vec_update_polar_timer'):
                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(HexrdConfig().rerender_needed.emit)
                self._beam_vec_update_polar_timer = timer
            HexrdConfig().flag_overlay_updates_for_all_materials()
            self._beam_vec_update_polar_timer.start(100)
            return

        # If it isn't polar, only overlay updates are needed
        if not self.iviewer or not hasattr(self.iviewer, 'instr'):
            return

        # Re-draw all overlays from scratch
        HexrdConfig().clear_overlay_data()

        bvec = HexrdConfig().instrument_config['beam']['vector']
        self.iviewer.instr.beam_vector = (bvec['azimuth'], bvec['polar_angle'])
        self.update_overlays()

    def show_cartesian(self):
        HexrdConfig().emit_update_status_bar('Loading Cartesian view...')
        if self.mode != ViewType.cartesian:
            self.clear()
            self.mode = ViewType.cartesian

        # Force a redraw when the pixel size changes.
        if (self.cartesian_res_config !=
                HexrdConfig().config['image']['cartesian']):
            self.cartesian_res_config = (
                HexrdConfig().config['image']['cartesian'].copy()
            )
            self.figure.clear()
            self.axes_images.clear()

        # Run the view generation in a background thread
        worker = AsyncWorker(cartesian_viewer)
        self.thread_pool.start(worker)

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_show_cartesian)
        worker.signals.error.connect(self.async_worker_error)

    def finish_show_cartesian(self, iviewer):
        self.iviewer = iviewer
        img = self.iviewer.img

        # It is important to persist the plot so that we don't reset the scale.
        rescale_image = True
        if len(self.axes_images) == 0:
            self.axis = self.figure.add_subplot(111)
            kwargs = {
                'X': img,
                'cmap': self.cmap,
                'norm': self.norm,
                'vmin': None,
                'vmax': None,
                'interpolation': 'none',
            }
            self.axes_images.append(self.axis.imshow(**kwargs))
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

        self.update_auto_picked_data()
        self.update_overlays()
        self.draw_detector_borders()

        msg = 'Cartesian view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    def show_polar(self):
        HexrdConfig().emit_update_status_bar('Loading polar view...')
        if self.mode != ViewType.polar:
            self.clear()
            self.mode = ViewType.polar

        polar_res_config = HexrdConfig().config['image']['polar']
        if self._polar_reset_needed(polar_res_config):
            # Reset the whole image when certain config items change
            self.clear()
            self.mode = ViewType.polar

        self.polar_res_config = polar_res_config.copy()

        # Run the view generation in a background thread
        worker = AsyncWorker(polar_viewer)
        self.thread_pool.start(worker)

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_show_polar)
        worker.signals.error.connect(self.async_worker_error)

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
            grid = plt.GridSpec(4, 1)

            # It is important to persist the plot so that we don't reset the
            # scale.
            if len(self.axes_images) == 0:
                self.axis = self.figure.add_subplot(grid[:3, 0])
                kwargs = {
                    'X': img,
                    'extent': extent,
                    'cmap': self.cmap,
                    'norm': self.norm,
                    'picker': True,
                    'interpolation': 'none',
                }
                self.axes_images.append(self.axis.imshow(**kwargs))
                self.axis.axis('auto')
                # Do not allow the axis to autoscale, which could happen if
                # overlays are drawn out-of-bounds
                self.axis.autoscale(False)
                self.axis.set_ylabel(r'$\eta$ (deg)')
                self.axis.label_outer()
            else:
                rescale_image = False
                self.axes_images[0].set_data(img)

            # Get the "tth" vector
            angular_grid = self.iviewer.angular_grid
            tth = np.degrees(angular_grid[1][0])

            if self.azimuthal_integral_axis is None:
                axis = self.figure.add_subplot(grid[3, 0], sharex=self.axis)
                data = (tth, self.compute_azimuthal_integral_sum())
                self.azimuthal_line_artist, = axis.plot(*data)
                HexrdConfig().last_azimuthal_integral_data = data

                self.azimuthal_integral_axis = axis
                axis.set_xlabel(r'2$\theta$ (deg)')
                axis.set_ylabel(r'Azimuthal Integration')
                self.update_wppf_plot()
            else:
                self.update_azimuthal_integral_plot()
                axis = self.azimuthal_integral_axis

            self.update_azimuthal_integral_plot_y_scale()
        else:
            if len(self.axes_images) == 0:
                self.axis = self.figure.add_subplot(111)
                kwargs = {
                    'X': img,
                    'cmap': self.cmap,
                    'norm': self.norm,
                    'picker': True,
                    'interpolation': 'none',
                }
                self.axes_images.append(self.axis.imshow(**kwargs))
                self.axis.set_xlabel(r'2$\theta$ (deg)')
                self.axis.set_ylabel(r'$\eta$ (deg)')
            else:
                rescale_image = False
                self.axes_images[0].set_data(img)

        if rescale_image:
            self.axis.relim()
            self.axis.autoscale_view()
            self.figure.tight_layout()

        self.update_auto_picked_data()
        self.update_overlays()
        self.draw_detector_borders()

        msg = 'Polar view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    def update_polar(self):
        if not self.iviewer:
            return

        self.iviewer.update_image()
        self.axes_images[0].set_data(self.iviewer.img)
        self.update_azimuthal_integral_plot()
        self.update_overlays()

    def async_worker_error(self, error):
        QMessageBox.critical(self, 'HEXRD', str(error[1]))
        msg = f'{str(self.mode)} view error!'
        HexrdConfig().emit_update_status_bar(msg)

        self.clear_figure()
        self.draw_idle()

    def set_cmap(self, cmap):
        self.cmap = cmap
        for axes_image in self.axes_images:
            axes_image.set_cmap(cmap)
        self.draw_idle()

    def set_norm(self, norm):
        self.norm = norm
        for axes_image in self.axes_images:
            axes_image.set_norm(norm)
        self.update_azimuthal_integral_plot_y_scale()
        self.draw_idle()

    def compute_azimuthal_integral_sum(self):
        # grab the polar image
        # !!! NOTE: currenlty not a masked image; just nans
        pimg = self.iviewer.img
        # !!! NOTE: visible polar masks have already been applied
        #           in polarview.py
        masked = np.ma.masked_array(pimg, mask=np.isnan(pimg))
        return masked.sum(axis=0) / np.sum(~masked.mask, axis=0)

    def update_azimuthal_integral_plot(self):
        if self.mode != ViewType.polar:
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
        data = (tth, self.compute_azimuthal_integral_sum())
        line.set_data(*data)

        HexrdConfig().last_azimuthal_integral_data = data

        # Update the wppf data if applicable
        self.update_wppf_plot()

        # Rescale the axes for the new data
        axis.relim()
        axis.autoscale_view(scalex=False)

    def update_azimuthal_integral_plot_y_scale(self):
        if self.azimuthal_integral_axis is not None:
            scale = 'log' if isinstance(self.norm, LogNorm) else 'linear'
            self.azimuthal_integral_axis.set_yscale(scale)
            HexrdConfig().azimuthal_integral_axis_scale = scale

    def update_wppf_plot(self):
        self.clear_wppf_plot()

        if not HexrdConfig().display_wppf_plot:
            return

        wppf_data = HexrdConfig().wppf_data
        axis = self.azimuthal_integral_axis
        line = self.azimuthal_line_artist
        if any(x is None for x in (wppf_data, axis, line)):
            return

        style = HexrdConfig().wppf_plot_style

        if style.get('marker', 'o') not in Line2D.filled_markers:
            # Marker is unfilled
            if 'edgecolors' in style:
                # Unfilled markers can't have edge colors.
                # Remove this to avoid a matplotlib warning.
                style = copy.deepcopy(style)
                del style['edgecolors']

        self.wppf_plot = axis.scatter(*wppf_data, **style)

    def detector_axis(self, detector_name):
        if self.mode in (ViewType.cartesian, ViewType.polar):
            # Only one axis for all detectors...
            return self.axis
        elif self.mode == ViewType.raw:
            titles = [x.get_title() for x in self.raw_axes]
            if detector_name not in titles:
                return None
            return self.raw_axes[titles.index(detector_name)]

    def update_auto_picked_data(self):
        self.clear_auto_picked_data_artists()

        xys = HexrdConfig().auto_picked_data
        if xys is None:
            return

        for det_key, panel in self.iviewer.instr.detectors.items():
            axis = self.detector_axis(det_key)
            if axis is None:
                # Probably, we are in tabbed view, and this is not the
                # right canvas for this detector...
                continue

            transform_func = transform_from_plain_cartesian_func(self.mode)
            rijs = transform_func(xys[det_key], panel, self.iviewer)
            artist, = axis.plot(rijs[:, 0], rijs[:, 1], 'm+')
            self.auto_picked_data_artists.append(artist)

    def on_detector_transform_modified(self, det):
        if self.mode is None:
            return

        self.iviewer.update_detector(det)
        if self.mode == ViewType.raw:
            # Only overlays need to be updated
            HexrdConfig().flag_overlay_updates_for_all_materials()
            self.update_overlays()
            return

        self.axes_images[0].set_data(self.iviewer.img)

        # This will only run if we are in polar mode
        self.update_azimuthal_integral_plot()

        # Update the detector borders if we are showing them
        # This will call self.draw_idle()
        self.draw_detector_borders()

        # In polar mode, the overlays are clipped to the detectors, so
        # they must be re-drawn as well
        if self.mode == ViewType.polar:
            HexrdConfig().flag_overlay_updates_for_all_materials()
            self.update_overlays()

    def export_current_plot(self, filename):
        if self.mode == ViewType.raw:
            msg = 'Must be in cartesisan or polar mode. Cannot export plot.'
            raise Exception(msg)

        if not self.iviewer:
            raise Exception('No iviewer. Cannot export polar plot')

        self.iviewer.write_image(filename)

    def _polar_reset_needed(self, new_polar_config):
        # If any of the entries on this list were changed, a reset is needed
        reset_needed_list = [
            'pixel_size_tth',
            'pixel_size_eta',
            'tth_min',
            'tth_max',
            'eta_min',
            'eta_max'
        ]

        for key in reset_needed_list:
            if self.polar_res_config[key] != new_polar_config[key]:
                return True

        return False

    def polar_show_snip1d(self):
        if self.mode != ViewType.polar:
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
            ax.set_xlabel(r'2$\theta$ (deg)')
            ax.set_ylabel(r'$\eta$ (deg)')
            self._snip1d_figure_cache = (fig, ax)
        else:
            fig, ax = self._snip1d_figure_cache

        algorithm = HexrdConfig().polar_snip1d_algorithm
        titles = ['Fast SNIP 1D', 'SNIP 1D', 'SNIP 2D']
        if algorithm < len(titles):
            title = titles[algorithm]
        else:
            title = f'Algorithm {algorithm}'
        ax.set_title(title)

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

        fig.canvas.draw_idle()
        fig.show()


def transform_from_plain_cartesian_func(mode):
    # Get a function to transform from plain cartesian coordinates
    # to whatever type of view we are in.

    # The functions all have arguments like the following:
    # xys, panel, iviewer

    def cart_to_pixel(xys, panel, iviewer):
        return panel.cartToPixel(xys)[:, [1, 0]]

    def transform_cart(xys, panel, iviewer):
        dplane = iviewer.dplane
        return panel.map_to_plane(xys, dplane.rmat, dplane.tvec)

    def cart_to_angles(xys, panel, iviewer):
        ang_crds, _ = panel.cart_to_angles(xys, tvec_c=iviewer.instr.tvec)
        ang_crds = np.degrees(ang_crds)
        ang_crds[:, 1] = mapAngle(ang_crds[:, 1],
                                  HexrdConfig().polar_res_eta_period,
                                  units='degrees')
        return ang_crds

    funcs = {
        ViewType.raw: cart_to_pixel,
        ViewType.cartesian: transform_cart,
        ViewType.polar: cart_to_angles,
    }

    if mode not in funcs:
        raise Exception(f'Unknown mode: {mode}')

    return funcs[mode]
