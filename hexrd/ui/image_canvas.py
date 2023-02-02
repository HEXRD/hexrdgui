import copy
import math

from PySide2.QtCore import QThreadPool, QTimer
from PySide2.QtWidgets import QMessageBox

from matplotlib.backends.backend_qt5agg import FigureCanvas

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle
import matplotlib.pyplot as plt

import numpy as np

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.calibration.cartesian_plot import cartesian_viewer
from hexrd.ui.calibration.polar_plot import polar_viewer
from hexrd.ui.calibration.raw_iviewer import raw_iviewer
from hexrd.ui.calibration.stereo_plot import stereo_viewer
from hexrd.ui.constants import OverlayType, ViewType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.snip_viewer_dialog import SnipViewerDialog
from hexrd.ui import utils
from hexrd.ui.utils.conversions import (
    angles_to_stereo, cart_to_angles, cart_to_pixels,
)
import hexrd.ui.constants


class ImageCanvas(FigureCanvas):

    def __init__(self, parent=None, image_names=None):
        self.figure = Figure(tight_layout=True)
        super().__init__(self.figure)

        self.raw_axes = {}  # only used for raw currently
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
        self.beam_marker_artists = []
        self.transform = lambda x: x
        self._last_stereo_size = None
        self.stereo_border_artists = []

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
        HexrdConfig().beam_marker_modified.connect(self.update_beam_marker)
        HexrdConfig().oscillation_stage_changed.connect(
            self.oscillation_stage_changed)
        HexrdConfig().polar_masks_changed.connect(self.polar_masks_changed)
        HexrdConfig().overlay_renamed.connect(self.overlay_renamed)

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
        HexrdConfig().last_unscaled_azimuthal_integral_data = None

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
            images_dict = self.scaled_image_dict

            # This will be used for drawing the rings
            self.iviewer = raw_iviewer()

            cols = 1
            if len(image_names) > 1:
                cols = 2

            rows = math.ceil(len(image_names) / cols)

            for i, name in enumerate(image_names):
                img = images_dict[name]
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
                self.raw_axes[name] = axis

            self.figure.tight_layout()
        else:
            images_dict = self.scaled_image_dict
            for i, name in enumerate(image_names):
                img = images_dict[name]
                self.axes_images[i].set_data(img)

        # This will call self.draw_idle()
        self.show_saturation()

        self.update_beam_marker()

        # Set the detectors to draw
        self.iviewer.detectors = list(self.raw_axes)
        self.update_auto_picked_data()
        self.update_overlays()

        # This always emits the full images dict, even if we are in
        # tabbed mode and this canvas is only displaying one of the
        # images from the dict.
        HexrdConfig().image_view_loaded.emit(images_dict)

        msg = 'Image view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    @property
    def unscaled_image_dict(self):
        # Returns a dict of the unscaled images
        if self.mode == ViewType.raw:
            return HexrdConfig().masked_images_dict
        else:
            # Masks are already applied...
            return {'img': self.iviewer.img}

    @property
    def unscaled_images(self):
        # Returns a list of the unscaled images
        if self.mode == ViewType.raw:
            return list(self.unscaled_image_dict.values())
        else:
            return [self.iviewer.img]

    @property
    def scaled_image_dict(self):
        # Returns a dict of the scaled images
        unscaled = self.unscaled_image_dict
        return {k: self.transform(v) for k, v in unscaled.items()}

    @property
    def scaled_images(self):
        return [self.transform(x) for x in self.unscaled_images]

    def remove_all_overlay_artists(self):
        while self.overlay_artists:
            key = next(iter(self.overlay_artists))
            self.remove_overlay_artists(key)

    def remove_overlay_artists(self, key):
        if key not in self.overlay_artists:
            return

        artists = self.overlay_artists[key]
        while artists:
            artists.pop(0).remove()
        del self.overlay_artists[key]

    def prune_overlay_artists(self):
        # Remove overlay artists that no longer have an overlay associated
        # with them
        overlay_names = [x.name for x in HexrdConfig().overlays]
        for key in list(self.overlay_artists):
            if key not in overlay_names:
                self.remove_overlay_artists(key)

    def overlay_renamed(self, old_name, new_name):
        if old_name in self.overlay_artists:
            self.overlay_artists[new_name] = self.overlay_artists[old_name]
            self.overlay_artists.pop(old_name)

    def overlay_axes_data(self, overlay):
        # Return the axes and data for drawing the overlay
        if not overlay.data:
            return []

        if self.mode == ViewType.raw:
            # If it's raw, there is data for each axis.
            # The title of each axis should match the detector key.
            # Add a safety check to ensure everything is synced up.
            if not all(x in overlay.data for x in self.raw_axes):
                return []

            return [(self.raw_axes[x], overlay.data[x]) for x in self.raw_axes]

        # If it is anything else, there is only one axis
        # Use the same axis for all of the data
        return [(self.axis, x) for x in overlay.data.values()]

    def overlay_draw_func(self, type):
        overlay_funcs = {
            OverlayType.powder: self.draw_powder_overlay,
            OverlayType.laue: self.draw_laue_overlay,
            OverlayType.rotation_series: self.draw_rotation_series_overlay,
        }

        if type not in overlay_funcs:
            raise Exception(f'Unknown overlay type: {type}')

        return overlay_funcs[type]

    def get_overlay_highlight_ids(self, overlay):
        highlights = overlay.highlights
        if not highlights:
            return []

        def recursive_get(cur, path):
            for p in path:
                cur = cur[p]
            return cur

        return [id(recursive_get(overlay.data, h)) for h in highlights]

    def draw_overlay(self, overlay):
        if not overlay.visible:
            return

        if overlay.name in self.overlay_artists:
            # It's already present. Skip it.
            return

        # Keep track of any overlays we need to highlight
        self.overlay_highlight_ids += self.get_overlay_highlight_ids(overlay)

        type = overlay.type
        style = overlay.style
        highlight_style = overlay.highlight_style
        for axis, data in self.overlay_axes_data(overlay):
            kwargs = {
                'artist_key': overlay.name,
                'axis': axis,
                'data': data,
                'style': style,
                'highlight_style': highlight_style,
            }
            self.overlay_draw_func(type)(**kwargs)

    def draw_powder_overlay(self, artist_key, axis, data, style,
                            highlight_style):
        rings = data['rings']
        rbnds = data['rbnds']
        rbnd_indices = data['rbnd_indices']

        data_style = style['data']
        ranges_style = style['ranges']

        highlight_indices = [i for i, x in enumerate(rings)
                             if id(x) in self.overlay_highlight_ids]

        artists = self.overlay_artists.setdefault(artist_key, [])
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
                if len(x) == 0:
                    # Skip over rings that are out of bounds
                    continue

                # Average the points together for the vertical line
                x = np.nanmean(x)
                artist = az_axis.axvline(x, **data_style)
                artists.append(artist)

            # Add the rbnds too
            for ind, pr in zip(rbnd_indices, rbnds):
                x, _ = self.extract_ring_coords(pr)
                if len(x) == 0:
                    # Skip over rbnds that are out of bounds
                    continue

                # Average the points together for the vertical line
                x = np.nanmean(x)

                current_style = copy.deepcopy(ranges_style)
                if len(ind) > 1:
                    # If rbnds are combined, override the color to red
                    current_style['c'] = 'r'

                artist = az_axis.axvline(x, **current_style)
                artists.append(artist)

    def draw_laue_overlay(self, artist_key, axis, data, style,
                          highlight_style):
        spots = data['spots']
        ranges = data['ranges']
        labels = data['labels']
        label_offsets = data['label_offsets']

        data_style = style['data']
        ranges_style = style['ranges']
        label_style = style['labels']

        highlight_indices = [i for i, x in enumerate(spots)
                             if id(x) in self.overlay_highlight_ids]

        artists = self.overlay_artists.setdefault(artist_key, [])
        for i, (x, y) in enumerate(spots):
            current_style = data_style
            if i in highlight_indices:
                current_style = highlight_style['data']

            artist = axis.scatter(x, y, **current_style)
            artists.append(artist)

            if labels:
                current_label_style = label_style
                if i in highlight_indices:
                    current_label_style = highlight_style['labels']

                kwargs = {
                    'x': x + label_offsets[0],
                    'y': y + label_offsets[1],
                    's': labels[i],
                    'clip_on': True,
                    **current_label_style,
                }
                artist = axis.text(**kwargs)
                artists.append(artist)

        for i, box in enumerate(ranges):
            current_style = ranges_style
            if i in highlight_indices:
                current_style = highlight_style['ranges']

            x, y = zip(*box)
            artist, = axis.plot(x, y, **current_style)
            artists.append(artist)

    def draw_rotation_series_overlay(self, artist_key, axis, data, style,
                                     highlight_style):
        is_aggregated = HexrdConfig().is_aggregated
        ome_range = HexrdConfig().omega_ranges
        aggregated = data['aggregated'] or is_aggregated or ome_range is None
        if not aggregated:
            ome_width = data['omega_width']
            ome_mean = np.mean(ome_range)
            full_range = (ome_mean - ome_width / 2, ome_mean + ome_width / 2)

        def in_range(x):
            return aggregated or full_range[0] <= x <= full_range[1]

        # Compute the indices that are in range for the current omega value
        ome_points = data['omegas']
        indices_in_range = [i for i, x in enumerate(ome_points) if in_range(x)]

        data_points = data['data']
        ranges = data['ranges']

        data_style = style['data']
        ranges_style = style['ranges']

        artists = self.overlay_artists.setdefault(artist_key, [])
        for i in indices_in_range:
            # data
            x, y = data_points[i]
            artist = axis.scatter(x, y, **data_style)
            artists.append(artist)

            # ranges
            if i >= len(ranges):
                continue

            x, y = zip(*ranges[i])
            artist, = axis.plot(x, y, **ranges_style)
            artists.append(artist)

    def redraw_overlay(self, overlay):
        # Remove the artists for this overlay
        self.remove_overlay_artists(overlay.name)

        # Redraw the overlay
        self.draw_overlay(overlay)

    def update_overlays(self):
        if HexrdConfig().loading_state:
            # Skip the request if we are loading state
            return

        # iviewer is required for drawing rings
        if not self.iviewer:
            return

        self.remove_all_overlay_artists()
        if not HexrdConfig().show_overlays:
            self.remove_all_overlay_artists()
            self.draw_idle()
            return

        # Remove any artists that:
        # 1. Are no longer in the list of overlays
        # 2. Are not visible
        # 3. Need updating
        self.prune_overlay_artists()
        for overlay in HexrdConfig().overlays:
            if overlay.update_needed or not overlay.visible:
                self.remove_overlay_artists(overlay.name)

        self.iviewer.update_overlay_data()

        self.overlay_highlight_ids = []
        for overlay in HexrdConfig().overlays:
            self.draw_overlay(overlay)

        self.draw_idle()

    def clear_detector_borders(self):
        while self.cached_detector_borders:
            self.cached_detector_borders.pop(0).remove()

        self.draw_idle()

    def draw_detector_borders(self):
        self.clear_detector_borders()

        # Need an iviewer
        if not self.iviewer:
            return

        # Make sure this is allowed by the configuration
        if not HexrdConfig().show_detector_borders:
            return

        borders = self.iviewer.all_detector_borders
        for border in borders.values():
            # Draw each line in the border
            for line in border:
                plot, = self.axis.plot(*line, color='y', lw=2)
                self.cached_detector_borders.append(plot)

    def clear_stereo_border_artists(self):
        while self.stereo_border_artists:
            self.stereo_border_artists.pop(0).remove()

        self.draw_idle()

    def draw_stereo_border(self):
        self.clear_stereo_border_artists()

        skip = (
            self.mode != ViewType.stereo or
            not HexrdConfig().stereo_show_border
        )
        if skip:
            return

        stereo_size = HexrdConfig().stereo_size
        radius = stereo_size / 2
        center = (stereo_size / 2, stereo_size / 2)

        circle = Circle(**{
            'xy': center,
            'radius': radius,
            'linewidth': 2,
            'edgecolor': 'black',
            'facecolor': 'none',
            'linestyle': '--',
        })
        artist = self.axis.add_patch(circle)
        self.stereo_border_artists.append(artist)

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

        # Only show the saturation in raw mode.
        if self.mode != ViewType.raw:
            return

        # Use the unscaled image data to determine saturation
        images_dict = self.unscaled_image_dict

        for img in self.axes_images:
            # The titles of the images are currently the detector names
            # If we change this in the future, we will need to change
            # our method for getting the saturation level as well.
            ax = img.axes
            detector_name = ax.get_title()
            detector = HexrdConfig().detector(detector_name)
            saturation_level = detector['saturation_level']['value']

            array = images_dict[detector_name]

            num_sat = (array >= saturation_level).sum()
            percent = num_sat / array.size * 100.0
            str_sat = 'Saturation: ' + str(num_sat)
            str_sat += '\n%5.3f %%' % percent

            t = ax.text(0.05, 0.05, str_sat, fontdict={'color': 'w'},
                        transform=ax.transAxes)
            self.saturation_texts.append(t)

        self.draw_idle()

    def clear_beam_marker(self):
        while self.beam_marker_artists:
            self.beam_marker_artists.pop(0).remove()

    def update_beam_marker(self):
        self.clear_beam_marker()

        # Need an iviewer
        if not self.iviewer:
            self.draw_idle()
            return

        # Make sure this is allowed by the configuration
        if not HexrdConfig().show_beam_marker:
            self.draw_idle()
            return

        style = HexrdConfig().beam_marker_style

        instr = self.iviewer.instr
        for det_key, panel in instr.detectors.items():
            func = transform_from_plain_cartesian_func(self.mode)
            cart_beam_position = panel.clip_to_panel(panel.beam_position,
                                                     buffer_edges=False)[0]
            if cart_beam_position.size == 0:
                continue

            beam_position = func(cart_beam_position, panel, self.iviewer)[0]
            if utils.has_nan(beam_position):
                continue

            axis = self.detector_axis(det_key)
            artist, = axis.plot(*beam_position, **style)
            self.beam_marker_artists.append(artist)

        self.draw_idle()

    def beam_vector_changed(self):
        if self.mode == ViewType.polar:
            # FIXME stereo: do something with stereo
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

        beam_config = HexrdConfig().instrument_config['beam']
        bvec = beam_config['vector']
        self.iviewer.instr.beam_vector = (bvec['azimuth'], bvec['polar_angle'])
        self.iviewer.instr.source_distance = beam_config['source_distance']
        self.update_overlays()
        self.update_beam_marker()

    def oscillation_stage_changed(self):
        if not self.iviewer or not hasattr(self.iviewer, 'instr'):
            return

        # Need to update the parameters on the instrument
        os_conf = HexrdConfig().instrument_config['oscillation_stage']
        self.iviewer.instr.chi = os_conf['chi']
        self.iviewer.instr.tvec = os_conf['translation']

        # Re-draw all overlays from scratch
        HexrdConfig().clear_overlay_data()
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
        img, = self.scaled_images

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
        self.update_beam_marker()

        HexrdConfig().image_view_loaded.emit({'img': img})

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
        img, = self.scaled_images
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
                self.axis.set_ylabel(r'$\eta$ [deg]')
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
                unscaled = (tth, self.compute_azimuthal_integral_sum(False))
                self.azimuthal_line_artist, = axis.plot(*data)
                HexrdConfig().last_unscaled_azimuthal_integral_data = unscaled

                self.azimuthal_integral_axis = axis
                axis.set_ylabel(r'Azimuthal Integration')
                self.update_wppf_plot()
            else:
                self.update_azimuthal_integral_plot()
                axis = self.azimuthal_integral_axis

            # Update the xlabel in case it was modified (via tth distortion)
            axis.set_xlabel(self.polar_xlabel)
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
                self.axis.set_ylabel(r'$\eta$ [deg]')
            else:
                rescale_image = False
                self.axes_images[0].set_data(img)

            # Update the xlabel in case it was modified (via tth distortion)
            self.axis.set_xlabel(self.polar_xlabel)

        if rescale_image:
            self.axis.relim()
            self.axis.autoscale_view()
            self.figure.tight_layout()

        self.update_auto_picked_data()
        self.update_overlays()
        self.draw_detector_borders()
        self.update_beam_marker()

        HexrdConfig().image_view_loaded.emit({'img': img})

        msg = 'Polar view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    def show_stereo(self):
        HexrdConfig().emit_update_status_bar('Loading stereo view...')

        stereo_size = HexrdConfig().config['image']['stereo']['stereo_size']
        last_stereo_size = self._last_stereo_size

        reset_needed = (
            self.mode != ViewType.stereo or
            stereo_size != last_stereo_size
        )
        if reset_needed:
            self.clear()
            self.mode = ViewType.stereo

        self._last_stereo_size = stereo_size

        # Run the view generation in a background thread
        worker = AsyncWorker(stereo_viewer)
        self.thread_pool.start(worker)

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_show_stereo)
        worker.signals.error.connect(self.async_worker_error)

    def finish_show_stereo(self, iviewer):
        self.iviewer = iviewer
        img, = self.scaled_images

        rescale_image = True
        if len(self.axes_images) == 0:
            self.axis = self.figure.add_subplot(111)
            kwargs = {
                'X': img,
                'extent': iviewer.extent,
                'cmap': self.cmap,
                'norm': self.norm,
                'picker': True,
                'interpolation': 'none',
            }
            self.axes_images.append(self.axis.imshow(**kwargs))
        else:
            rescale_image = False
            self.axes_images[0].set_data(img)

        if rescale_image:
            self.axis.relim()
            self.axis.autoscale_view()
            self.figure.tight_layout()

        self.draw_stereo_border()
        self.update_auto_picked_data()
        self.update_overlays()
        self.draw_detector_borders()
        self.update_beam_marker()

        HexrdConfig().image_view_loaded.emit({'img': img})

        msg = 'Stereo view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    @property
    def polar_xlabel(self):
        overlay = HexrdConfig().polar_tth_distortion_overlay
        if overlay is None:
            return r'2$\theta_{nom}$ [deg]'

        xlabel = r'2$\theta_{sam}$'
        standoff = overlay.tth_distortion_kwargs.get('layer_standoff', None)
        if standoff is not None:
            xlabel += f'@{standoff * 1e3:.5g}' + r'${\mu}m$'

        xlabel += ' [deg]'

        return xlabel

    def polar_masks_changed(self):
        skip = (
            not self.iviewer or
            self.mode not in (ViewType.polar, ViewType.stereo) or
            (self.mode == ViewType.stereo and
             not self.iviewer.project_from_polar)
        )
        if skip:
            return

        self.iviewer.reapply_masks()
        self.axes_images[0].set_data(self.scaled_images[0])
        self.update_azimuthal_integral_plot()
        self.update_overlays()
        self.draw_idle()

    def async_worker_error(self, error):
        QMessageBox.critical(self, 'HEXRD', str(error[1]))
        msg = f'{str(self.mode)} view error!'
        HexrdConfig().emit_update_status_bar(msg)

        self.clear_figure()
        self.draw_idle()

    def set_scaling(self, transform):
        # Apply the scaling, and set the data
        self.transform = transform
        for axes_image, img in zip(self.axes_images, self.scaled_images):
            axes_image.set_data(img)

        self.update_azimuthal_integral_plot()
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
        self.draw_idle()

    def compute_azimuthal_integral_sum(self, scaled=True):
        # grab the polar image
        # !!! NOTE: currently not a masked image; just nans
        if scaled:
            pimg = self.scaled_images[0]
        else:
            pimg = self.unscaled_images[0]
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

        unscaled = (tth, self.compute_azimuthal_integral_sum(scaled=False))
        HexrdConfig().last_unscaled_azimuthal_integral_data = unscaled

        # Update the wppf data if applicable
        self.update_wppf_plot()

        # Rescale the axes for the new data
        axis.relim()
        axis.autoscale_view(scalex=False)

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
        if self.mode == ViewType.raw:
            if detector_name not in self.raw_axes:
                return None
            return self.raw_axes[detector_name]
        else:
            # Only one axis for all detectors...
            return self.axis

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
        if HexrdConfig().loading_state:
            # Skip the request if we are loading state
            return

        if self.mode is None:
            return

        self.iviewer.update_detector(det)
        if self.mode == ViewType.raw:
            # Only overlays need to be updated
            HexrdConfig().flag_overlay_updates_for_all_materials()
            self.update_beam_marker()

            if HexrdConfig().any_intensity_corrections:
                # A re-render may be needed, as the images may change
                HexrdConfig().rerender_needed.emit()
            else:
                # Only overlays need updating
                self.update_overlays()

            return

        self.axes_images[0].set_data(self.scaled_images[0])

        # This will only run if we are in polar mode
        self.update_azimuthal_integral_plot()

        # Update the detector borders if we are showing them
        # This will call self.draw_idle()
        self.draw_detector_borders()

        # In polar/stereo mode, the overlays are clipped to the detectors, so
        # they must be re-drawn as well
        if self.mode in (ViewType.polar, ViewType.stereo):
            HexrdConfig().flag_overlay_updates_for_all_materials()
            self.update_overlays()

    def export_current_plot(self, filename):
        allowed_view_types = [
            ViewType.cartesian,
            ViewType.polar,
            ViewType.stereo,
        ]
        if self.mode not in allowed_view_types:
            msg = (
                f'View mode not implemented: {self.mode}. Cannot export.'
            )
            raise NotImplementedError(msg)

        if not self.iviewer:
            raise Exception('No iviewer. Cannot export')

        self.iviewer.write_image(filename)

    def export_to_maud(self, filename):
        if self.mode != ViewType.polar:
            msg = 'Must be in polar mode. Cannot export.'
            raise Exception(msg)

        if not self.iviewer:
            raise Exception('No iviewer. Cannot export')

        self.iviewer.write_maud(filename)

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
            return

        extent = self.iviewer._extent

        if self.iviewer.snip_background is not None:
            background = self.iviewer.snip_background
        else:
            # We have to run it ourselves...
            img = self.iviewer.raw_rescaled_img

            no_nan_methods = [utils.SnipAlgorithmType.Fast_SNIP_1D]
            if HexrdConfig().polar_snip1d_algorithm not in no_nan_methods:
                img[self.iviewer.raw_mask] = np.nan

            background = utils.run_snip1d(img)

        self._snip_viewer_dialog = SnipViewerDialog(background, extent)
        self._snip_viewer_dialog.show()


def transform_from_plain_cartesian_func(mode):
    # Get a function to transform from plain cartesian coordinates
    # to whatever type of view we are in.

    # The functions all have arguments like the following:
    # xys, panel, iviewer

    def to_pixels(xys, panel, iviewer):
        return cart_to_pixels(xys, panel)

    def transform_cart(xys, panel, iviewer):
        dplane = iviewer.dplane
        return panel.map_to_plane(xys, dplane.rmat, dplane.tvec)

    def to_angles(xys, panel, iviewer):
        kwargs = {
            'xys': xys,
            'panel': panel,
            'eta_period': HexrdConfig().polar_res_eta_period,
            'tvec_s': iviewer.instr.tvec,
        }
        return cart_to_angles(**kwargs)

    def to_stereo(xys, panel, iviewer):
        # First convert to angles, then to stereo from there
        angs = np.radians(to_angles(xys, panel, iviewer))
        return angles_to_stereo(
            angs,
            iviewer.instr,
            HexrdConfig().stereo_size,
        )

    funcs = {
        ViewType.raw: to_pixels,
        ViewType.cartesian: transform_cart,
        ViewType.polar: to_angles,
        ViewType.stereo: to_stereo,
    }

    if mode not in funcs:
        raise Exception(f'Unknown mode: {mode}')

    return funcs[mode]
