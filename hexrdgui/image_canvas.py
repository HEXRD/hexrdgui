import copy
import math

from PySide6.QtCore import QThreadPool, QTimer, Signal, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from matplotlib.backends.backend_qtagg import FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle
from matplotlib.ticker import AutoLocator, FuncFormatter

import matplotlib.pyplot as plt
import matplotlib.transforms as tx

import numpy as np

from hexrdgui.async_worker import AsyncWorker
from hexrdgui.blit_manager import BlitManager
from hexrdgui.calibration.cartesian_plot import cartesian_viewer
from hexrdgui.calibration.polar_plot import polar_viewer
from hexrdgui.calibration.raw_iviewer import raw_iviewer
from hexrdgui.calibration.stereo_plot import stereo_viewer
from hexrdgui.constants import OverlayType, PolarXAxisType, ViewType
from hexrdgui.create_hedm_instrument import create_view_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.create_polar_mask import create_polar_line_data_from_raw
from hexrdgui.masking.mask_manager import MaskManager
from hexrdgui.snip_viewer_dialog import SnipViewerDialog
from hexrdgui import utils
from hexrdgui.utils.array import split_array
from hexrdgui.utils.conversions import (
    angles_to_stereo, cart_to_angles, cart_to_pixels, q_to_tth, tth_to_q,
)
from hexrdgui.utils.tth_distortion import apply_tth_distortion_if_needed


class ImageCanvas(FigureCanvas):

    cmap_modified = Signal()
    norm_modified = Signal()
    transform_modified = Signal()

    def __init__(self, parent=None, image_names=None):
        self.figure = Figure(tight_layout=True)
        super().__init__(self.figure)

        self.raw_axes = {}  # only used for raw currently
        self.axes_images = []
        self.cached_detector_borders = []
        self.saturation_texts = []
        self.cmap = HexrdConfig().default_cmap
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
        self.azimuthal_overlay_artists = []
        self.blit_manager = BlitManager(self)
        self.raw_view_images_dict = {}
        self._mask_boundary_artists = []

        # Track the current mode so that we can more lazily clear on change.
        self.mode = None

        # Track the pixel size
        self.cartesian_res_config = (
            HexrdConfig().config['image']['cartesian'].copy()
        )
        self.polar_res_config = HexrdConfig().config['image']['polar'].copy()

        if image_names is not None:
            self.load_images(image_names)

        self.setFocusPolicy(Qt.ClickFocus)

        self.setup_connections()

    def setup_connections(self):
        HexrdConfig().overlay_config_changed.connect(self.update_overlays)
        HexrdConfig().show_saturation_level_changed.connect(
            self.show_saturation)
        HexrdConfig().show_stereo_border_changed.connect(
            self.draw_stereo_border)
        HexrdConfig().detector_transforms_modified.connect(
            self.on_detector_transforms_modified)
        HexrdConfig().rerender_detector_borders.connect(
            self.draw_detector_borders)
        HexrdConfig().rerender_wppf.connect(self.draw_wppf)
        HexrdConfig().rerender_auto_picked_data.connect(
            self.draw_auto_picked_data)
        HexrdConfig().beam_vector_changed.connect(self.beam_vector_changed)
        HexrdConfig().beam_marker_modified.connect(self.update_beam_marker)
        HexrdConfig().oscillation_stage_changed.connect(
            self.oscillation_stage_changed)
        MaskManager().polar_masks_changed.connect(self.polar_masks_changed)
        HexrdConfig().overlay_renamed.connect(self.overlay_renamed)
        HexrdConfig().azimuthal_options_modified.connect(
            self.update_azimuthal_integral_plot)
        HexrdConfig().azimuthal_plot_save_requested.connect(
            self.save_azimuthal_plot)
        HexrdConfig().polar_x_axis_type_changed.connect(
            self.on_polar_x_axis_type_changed)
        HexrdConfig().beam_energy_modified.connect(
            self.on_beam_energy_modified)

    @property
    def thread_pool(self):
        return QThreadPool.globalInstance()

    def __del__(self):
        # This is so that the figure can be cleaned up
        plt.close(self.figure)

    def clear(self):
        self.iviewer = None
        self.mode = None
        self.raw_view_images_dict = {}
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
        self.clear_azimuthal_overlay_artists()
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
            images_dict = self.scaled_display_image_dict

            # This will be used for drawing the rings
            self.iviewer = raw_iviewer()

            if HexrdConfig().stitch_raw_roi_images:
                # The image_names is actually a list of group names
                images_dict = self.iviewer.raw_images_to_stitched(
                    image_names, images_dict)

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
            images_dict = self.scaled_display_image_dict
            if HexrdConfig().stitch_raw_roi_images:
                # The image_names is actually a list of group names
                images_dict = self.iviewer.raw_images_to_stitched(
                    image_names, images_dict)

            for i, name in enumerate(image_names):
                img = images_dict[name]
                self.axes_images[i].set_data(img)

        if MaskManager().contains_border_only_masks:
            # Create a computed version for the images dict
            computed_images_dict = self.scaled_image_dict
            if HexrdConfig().stitch_raw_roi_images:
                computed_images_dict = self.iviewer.raw_images_to_stitched(
                    image_names, computed_images_dict)
        else:
            # The computed image is the same as the display image.
            # Save some computation time for faster rendering.
            computed_images_dict = images_dict

        self.raw_view_images_dict = computed_images_dict
        self.clear_mask_boundaries()
        for name, axis in self.raw_axes.items():
            self.draw_mask_boundaries(axis, name)

        # This will call self.draw_idle()
        self.show_saturation()

        self.update_beam_marker()
        self.update_auto_picked_data()
        self.update_overlays()

        # This always emits the full images dict, even if we are in
        # tabbed mode and this canvas is only displaying one of the
        # images from the dict.
        HexrdConfig().image_view_loaded.emit(images_dict)

        msg = 'Image view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    def create_image_dict(self, display=False):
        # Returns a dict of the unscaled computation images
        if self.mode == ViewType.raw:
            return HexrdConfig().create_masked_images_dict(fill_value=np.nan,
                                                           display=display)
        else:
            # Masks are already applied...
            img = self.iviewer.display_img if display else self.iviewer.img
            return {'img': img}

    @property
    def unscaled_image_dict(self):
        return self.create_image_dict(display=False)

    @property
    def unscaled_display_image_dict(self):
        return self.create_image_dict(display=True)

    @property
    def unscaled_images(self):
        # Returns a list of the unscaled computation images
        return list(self.unscaled_image_dict.values())

    @property
    def unscaled_display_images(self):
        # Returns a list of the unscaled display images
        return list(self.unscaled_display_image_dict.values())

    def create_scaled_image_dict(self, display=False):
        if display:
            unscaled = self.unscaled_display_image_dict
        else:
            unscaled = self.unscaled_image_dict
        return {k: self.transform(v) for k, v in unscaled.items()}

    @property
    def scaled_image_dict(self):
        # Returns a dict of the scaled computation images
        return self.create_scaled_image_dict(display=False)

    @property
    def scaled_display_image_dict(self):
        # Returns a dict of the scaled display images
        return self.create_scaled_image_dict(display=True)

    @property
    def scaled_images(self):
        return list(self.scaled_image_dict.values())

    @property
    def scaled_display_images(self):
        return list(self.scaled_display_image_dict.values())

    @property
    def blit_artists(self):
        return self.blit_manager.artists

    @property
    def overlay_artists(self):
        return self.blit_artists.setdefault('overlays', {})

    def remove_all_overlay_artists(self):
        self.blit_manager.remove_artists('overlays')
        self.blit_manager.artists['overlays'] = {}

    def remove_overlay_artists(self, key):
        self.blit_manager.remove_artists('overlays', key)

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
            data = self.iviewer.create_overlay_data(overlay)

            # If it's raw, there is data for each axis.
            # The title of each axis should match the detector key.
            # Add a safety check to ensure everything is synced up.
            if not all(x in data for x in self.raw_axes):
                return []

            return [(self.raw_axes[x], x, data[x]) for x in self.raw_axes]

        # If it is anything else, there is only one axis
        # Use the same axis for all of the data
        return [(self.axis, k, v) for k, v in overlay.data.items()]

    def overlay_draw_func(self, type):
        overlay_funcs = {
            OverlayType.powder: self.draw_powder_overlay,
            OverlayType.laue: self.draw_laue_overlay,
            OverlayType.rotation_series: self.draw_rotation_series_overlay,
            OverlayType.const_chi: self.draw_const_chi_overlay,
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
        for axis, det_key, data in self.overlay_axes_data(overlay):
            kwargs = {
                'artist_key': overlay.name,
                'det_key': det_key,
                'axis': axis,
                'data': data,
                'style': style,
                'highlight_style': highlight_style,
            }
            self.overlay_draw_func(type)(**kwargs)

        if self.mode == ViewType.polar and overlay.type == OverlayType.powder:
            self.draw_azimuthal_powder_lines(overlay)

    def draw_powder_overlay(self, artist_key, det_key, axis, data, style,
                            highlight_style):
        rings = data['rings']
        ranges = data['rbnds']
        rbnd_indices = data['rbnd_indices']

        data_style = style['data']
        ranges_style = style['ranges']

        merged_ranges_style = copy.deepcopy(ranges_style)
        merged_ranges_style['c'] = 'r'

        overlay_artists = self.overlay_artists.setdefault(artist_key, {})
        artists = overlay_artists.setdefault(det_key, {})

        highlight_indices = []

        if self.overlay_highlight_ids:
            # Split up highlighted and non-highlighted components for all
            highlight_indices = [i for i, x in enumerate(rings)
                                 if id(x) in self.overlay_highlight_ids]

        def split(data):
            if not highlight_indices or len(data) == 0:
                return [], data

            return split_array(data, highlight_indices)

        h_rings, rings = split(rings)

        # Find merged ranges and highlighted ranges
        # Some ranges will be both "merged" and "highlighted"
        merged_ranges = []
        h_ranges = []
        reg_ranges = []

        found = False
        for i, ind in enumerate(rbnd_indices):
            if len(ind) > 1:
                merged_ranges.append(ranges[i])
                found = True

            if highlight_indices and any(x in highlight_indices for x in ind):
                h_ranges.append(ranges[i])
                found = True

            if not found:
                # Not highlighted or merged
                reg_ranges.append(ranges[i])

            found = False

        def plot(data, key, kwargs):
            # This logic was repeated
            if len(data) != 0:
                artists[key], = axis.plot(*np.vstack(data).T, animated=True,
                                          **kwargs)

        plot(rings, 'rings', data_style)
        plot(h_rings, 'h_rings', highlight_style['data'])

        plot(reg_ranges, 'ranges', ranges_style)
        plot(merged_ranges, 'merged_ranges', merged_ranges_style)
        # Highlighting goes after merged ranges to get precedence
        plot(h_ranges, 'h_ranges', highlight_style['ranges'])

    def draw_azimuthal_powder_lines(self, overlay):
        az_axis = self.azimuthal_integral_axis
        if az_axis is None or not overlay.hkl_means:
            # Can't draw
            return

        style = overlay.style
        data_style = style['data']
        ranges_style = style['ranges']

        merged_ranges_style = copy.deepcopy(ranges_style)
        merged_ranges_style['c'] = 'r'

        overlay_artists = self.overlay_artists.setdefault(overlay.name, {})
        artists = overlay_artists.setdefault('__lineout', {})

        trans = tx.blended_transform_factory(az_axis.transData,
                                             az_axis.transAxes)

        rings = []
        ranges = []
        merged_ranges = []
        for data in overlay.hkl_means.values():
            rings.append(data['rings'])
            if 'rbnds' in data:
                joined = [data['rbnds']['lower'], data['rbnds']['upper']]
                if data['rbnds']['merged']:
                    merged_ranges.extend(joined)
                else:
                    ranges.extend(joined)

        def az_plot(data, key, kwargs):
            if len(data) == 0:
                return

            xmeans = np.asarray(data)

            x = np.repeat(xmeans, 3)
            y = np.tile([0, 1, np.nan], len(xmeans))

            artists[key], = az_axis.plot(x, y, transform=trans,
                                         animated=True, **kwargs)

        az_plot(rings, 'rings', data_style)
        az_plot(ranges, 'ranges', ranges_style)
        az_plot(merged_ranges, 'merged_ranges', merged_ranges_style)

    def draw_laue_overlay(self, artist_key, det_key, axis, data, style,
                          highlight_style):
        spots = data['spots']
        ranges = data['ranges']
        labels = data['labels']
        label_offsets = data['label_offsets']

        data_style = style['data']
        ranges_style = style['ranges']
        label_style = style['labels']

        highlight_indices = []

        if self.overlay_highlight_ids:
            # Split up highlighted and non-highlighted components for all
            highlight_indices = [i for i, x in enumerate(spots)
                                 if id(x) in self.overlay_highlight_ids]

        def split(data):
            if not highlight_indices or len(data) == 0:
                return [], data

            return split_array(data, highlight_indices)

        h_spots, spots = split(spots)
        h_ranges, ranges = split(ranges)
        h_labels, labels = split(labels)

        overlay_artists = self.overlay_artists.setdefault(artist_key, {})
        artists = overlay_artists.setdefault(det_key, {})

        def scatter(data, key, kwargs):
            # This logic was repeated
            if len(data) != 0:
                artists[key] = axis.scatter(*np.asarray(data).T, animated=True,
                                            **kwargs)

        def plot(data, key, kwargs):
            # This logic was repeated
            if len(data) != 0:
                artists[key], = axis.plot(*np.vstack(data).T, animated=True,
                                          **kwargs)

        # Draw spots and highlighted spots
        scatter(spots, 'spots', data_style)
        scatter(h_spots, 'h_spots', highlight_style['data'])

        # Draw ranges and highlighted ranges
        plot(ranges, 'ranges', ranges_style)
        plot(h_ranges, 'h_ranges', highlight_style['ranges'])

        # Draw labels and highlighted labels
        if len(labels) or len(h_labels):
            def plot_label(x, y, label, style):
                kwargs = {
                    'x': x + label_offsets[0],
                    'y': y + label_offsets[1],
                    's': label,
                    'clip_on': True,
                    **style,
                }
                return axis.text(**kwargs)

            # I don't know of a way to use a single artist for all labels.
            # FIXME: figure out how to make this faster, if needed.
            artists.setdefault('labels', [])
            for label, (x, y) in zip(labels, spots):
                artists['labels'].append(plot_label(x, y, label, label_style))

            # I don't know of a way to use a single artist for all labels.
            # FIXME: figure out how to make this faster, if needed.
            artists.setdefault('h_labels', [])
            style = highlight_style['labels']
            for label, (x, y) in zip(h_labels, h_spots):
                artists['h_labels'].append(plot_label(x, y, label, style))

    def draw_rotation_series_overlay(self, artist_key, det_key, axis, data,
                                     style, highlight_style):
        is_aggregated = HexrdConfig().is_aggregated
        ome_range = HexrdConfig().omega_ranges
        aggregated = data['aggregated'] or is_aggregated or ome_range is None

        # Compute the indices that are in range for the current omega value
        ome_points = data['omegas']

        if aggregated:
            # This means we will keep all
            slicer = slice(None)
        else:
            ome_width = data['omega_width']
            ome_mean = np.mean(ome_range)
            ome_min = ome_mean - ome_width / 2
            ome_max = ome_mean + ome_width / 2

            in_range = np.logical_and(ome_min <= ome_points,
                                      ome_points <= ome_max)
            slicer = np.where(in_range)

        data_points = data['data']
        ranges = data['ranges']

        data_style = style['data']
        ranges_style = style['ranges']

        if len(data_points) == 0:
            return

        sliced_data = data_points[slicer]
        if len(sliced_data) == 0:
            return

        overlay_artists = self.overlay_artists.setdefault(artist_key, {})
        artists = overlay_artists.setdefault(det_key, {})

        artists['data'] = axis.scatter(*sliced_data.T, animated=True,
                                       **data_style)

        sliced_ranges = np.asarray(ranges)[slicer]
        artists['ranges'], = axis.plot(*np.vstack(sliced_ranges).T,
                                       animated=True, **ranges_style)

    def draw_const_chi_overlay(self, artist_key, det_key, axis, data, style,
                               highlight_style):
        points = data['data']
        data_style = style['data']

        overlay_artists = self.overlay_artists.setdefault(artist_key, {})
        artists = overlay_artists.setdefault(det_key, {})

        highlight_indices = []

        if self.overlay_highlight_ids:
            # Split up highlighted and non-highlighted components for all
            highlight_indices = [i for i, x in enumerate(points)
                                 if id(x) in self.overlay_highlight_ids]

        def split(data):
            if not highlight_indices or len(data) == 0:
                return [], data

            return split_array(data, highlight_indices)

        h_points, points = split(points)

        def plot(data, key, kwargs):
            # This logic was repeated
            if len(data) != 0:
                artists[key], = axis.plot(*np.vstack(data).T, animated=True,
                                          **kwargs)

        plot(points, 'points', data_style)
        plot(h_points, 'h_points', highlight_style['data'])

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
        if not HexrdConfig().show_overlays or not HexrdConfig().overlays:
            # Avoid proceeding if possible, as updating the blit manager
            # can be time consuming.
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

        self.blit_manager.update()

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

        def compute_saturation_and_size(detector_name):
            detector = HexrdConfig().detector(detector_name)
            saturation_level = detector['saturation_level']['value']

            array = images_dict[detector_name]

            num_sat = (array >= saturation_level).sum()

            return num_sat, array.size

        for img in self.axes_images:
            # The titles of the images are currently the detector names
            # If we change this in the future, we will need to change
            # our method for getting the saturation level as well.
            ax = img.axes

            axes_title = ax.get_title()

            if HexrdConfig().stitch_raw_roi_images:
                # The axes title is the group name
                det_keys = self.iviewer.roi_groups[axes_title]
                results = [compute_saturation_and_size(x) for x in det_keys]
                num_sat = sum(x[0] for x in results)
                size = sum(x[1] for x in results)
            else:
                # The axes_title is the detector name
                num_sat, size = compute_saturation_and_size(axes_title)

            percent = num_sat / size * 100.0
            str_sat = f'Saturation: {num_sat}\n%{percent:5.3f}'

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
            axis = self.detector_axis(det_key)
            if axis is None:
                # Probably, we are in tabbed view, and this is not the
                # right canvas for this detector...
                continue

            func = transform_from_plain_cartesian_func(self.mode)
            cart_beam_position = panel.clip_to_panel(panel.beam_position,
                                                     buffer_edges=False)[0]
            if cart_beam_position.size == 0:
                continue

            beam_position = func(cart_beam_position, panel, self.iviewer)[0]
            if utils.has_nan(beam_position):
                continue

            artist, = axis.plot(*beam_position, **style)
            self.beam_marker_artists.append(artist)

        self.draw_idle()

    def beam_vector_changed(self):
        if self.mode == ViewType.polar or self.is_stereo_from_polar:
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
        if self.mode != ViewType.cartesian:
            # Image mode was switched during generation. Ignore this.
            return

        self.iviewer = iviewer
        img, = self.scaled_display_images

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
        self.draw_detector_borders()
        self.update_beam_marker()
        self.update_overlays()

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
        if self.mode != ViewType.polar:
            # Image mode was switched during generation. Ignore this.
            return

        self.iviewer = iviewer
        img, = self.scaled_display_images
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

            self.update_mask_boundaries(self.axis)

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
                axis.set_ylabel(r'Azimuthal Average')
                self.update_azimuthal_plot_overlays()
                self.update_wppf_plot()

                # Set up formatting for the x-axis
                default_formatter = axis.xaxis.get_major_formatter()
                f = self.format_polar_x_major_ticks
                formatter = PolarXAxisFormatter(default_formatter, f)
                axis.xaxis.set_major_formatter(formatter)

                # Set our custom tick locators as well
                self.axis.xaxis.set_major_locator(PolarXAxisTickLocator(self))
                axis.xaxis.set_major_locator(PolarXAxisTickLocator(self))
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
        self.draw_detector_borders()
        self.update_beam_marker()
        self.update_overlays()

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
        if self.mode != ViewType.stereo:
            # Image mode was switched during generation. Ignore this.
            return

        self.iviewer = iviewer
        img, = self.scaled_display_images

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
                # We want to flip the whole stereo image along the x-axis
                'origin': 'lower',
            }
            self.axes_images.append(self.axis.imshow(**kwargs))
        else:
            rescale_image = False
            self.axes_images[0].set_data(img)

        if rescale_image:
            self.axis.relim()
            self.axis.autoscale_view()
            self.figure.tight_layout()

        self.update_mask_boundaries(self.axis)

        self.draw_stereo_border()
        self.update_auto_picked_data()
        self.draw_detector_borders()
        self.update_beam_marker()
        self.update_overlays()

        HexrdConfig().image_view_loaded.emit({'img': img})

        msg = 'Stereo view loaded!'
        HexrdConfig().emit_update_status_bar(msg)

    def on_beam_energy_modified(self):
        # Update the beam energy on our instrument if we have one
        if not self.iviewer:
            # No need to do anything
            return

        # Update the beam energy on the instrument
        self.iviewer.instr.beam_energy = HexrdConfig().beam_energy

    @property
    def polar_x_axis_type(self):
        return HexrdConfig().polar_x_axis_type

    def on_polar_x_axis_type_changed(self):
        # Update the x-label
        self.azimuthal_integral_axis.set_xlabel(self.polar_xlabel)

        # Still need to draw if the x-label was modified
        self.draw_idle()

    def format_polar_x_major_ticks(self, x, pos=None):
        if self.mode != ViewType.polar or not self.iviewer:
            # No need to do anything
            return ''

        xaxis = self.azimuthal_integral_axis.xaxis
        x_axis_type = self.polar_x_axis_type
        if x_axis_type == PolarXAxisType.tth:
            # Use the default formatter.
            formatter = xaxis.get_major_formatter()
            return formatter.default_formatter(x, pos)
        elif x_axis_type == PolarXAxisType.q:
            q = tth_to_q(x, self.iviewer.instr.beam_energy)
            return f'{q:0.4g}'

        raise NotImplementedError(x_axis_type)

    def polar_tth_to_x_type(self, array):
        x_axis_type = self.polar_x_axis_type
        if x_axis_type == PolarXAxisType.tth:
            # Nothing to do
            return array
        elif x_axis_type == PolarXAxisType.q:
            return tth_to_q(array, self.iviewer.instr.beam_energy)

        raise NotImplementedError(x_axis_type)

    def polar_x_type_to_tth(self, array):
        x_axis_type = self.polar_x_axis_type
        if x_axis_type == PolarXAxisType.tth:
            # Nothing to do
            return array
        elif x_axis_type == PolarXAxisType.q:
            return q_to_tth(array, self.iviewer.instr.beam_energy)

        raise NotImplementedError(x_axis_type)

    @property
    def polar_xlabel_subscript(self):
        obj = HexrdConfig().polar_tth_distortion_object
        if obj is None:
            return 'nom'

        if obj.pinhole_distortion_type == 'SampleLayerDistortion':
            return 'sam'
        else:
            return 'pin'

    @property
    def polar_xlabel_suffix(self):
        obj = HexrdConfig().polar_tth_distortion_object
        if obj and obj.pinhole_distortion_type == 'SampleLayerDistortion':
            standoff = obj.pinhole_distortion_kwargs.get('layer_standoff',
                                                         None)
            if standoff is not None:
                return f'@{standoff * 1e3:.5g}' + r'${\mu}m$'

        return ''

    @property
    def polar_xlabel(self):
        subscript = self.polar_xlabel_subscript
        suffix = self.polar_xlabel_suffix

        x_axis_type = self.polar_x_axis_type
        if x_axis_type == PolarXAxisType.tth:
            return rf'2$\theta_{{{subscript}}}${suffix} [deg]'
        elif x_axis_type == PolarXAxisType.q:
            return rf'$Q_{{{subscript}}}${suffix} [$\AA^{{-1}}$]'

        raise NotImplementedError(x_axis_type)

    @property
    def is_stereo_from_polar(self):
        return (
            self.mode == ViewType.stereo and
            self.iviewer and
            self.iviewer.project_from_polar
        )

    def polar_masks_changed(self):
        skip = (
            not self.iviewer or
            self.mode not in (ViewType.polar, ViewType.stereo) or
            (self.mode == ViewType.stereo and not self.is_stereo_from_polar)
        )
        if skip:
            return

        self.update_mask_boundaries(self.axis)
        self.iviewer.reapply_masks()
        self.axes_images[0].set_data(self.scaled_display_images[0])
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
        for axes_img, img in zip(self.axes_images, self.scaled_display_images):
            axes_img.set_data(img)

        self.update_azimuthal_integral_plot()
        self.draw_idle()
        self.transform_modified.emit()

    def set_cmap(self, cmap):
        self.cmap = cmap
        for axes_image in self.axes_images:
            axes_image.set_cmap(cmap)
        self.draw_idle()
        self.cmap_modified.emit()

    def set_norm(self, norm):
        self.norm = norm
        for axes_image in self.axes_images:
            axes_image.set_norm(norm)
        self.draw_idle()
        self.norm_modified.emit()

    def compute_azimuthal_integral_sum(self, scaled=True):
        # grab the polar image
        # !!! NOTE: currently not a masked image; just nans
        if scaled and HexrdConfig().polar_apply_scaling_to_lineout:
            pimg = self.scaled_images[0]
        else:
            pimg = self.unscaled_images[0]
        # !!! NOTE: visible polar masks have already been applied
        #           in polarview.py
        masked = np.ma.masked_array(pimg, mask=np.isnan(pimg))
        offset = HexrdConfig().azimuthal_offset
        return masked.sum(axis=0) / np.sum(~masked.mask, axis=0) + offset

    def clear_azimuthal_overlay_artists(self):
        while self.azimuthal_overlay_artists:
            item = self.azimuthal_overlay_artists.pop(0)
            for artist in item['artists'].values():
                artist.remove()

    def save_azimuthal_plot(self):
        if self.mode != ViewType.polar:
            # Nothing to do. Just return.
            return

        # Save just the second axis (the azimuthal integral plot)
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self, 'Save Azimuthal Integral Plot', HexrdConfig().working_dir)

        if not selected_file:
            return
        # Find and invert the physical inches from the bottom left corner
        size = self.figure.dpi_scale_trans.inverted()
        # Get the bbox for the second plot
        extent = self.azimuthal_integral_axis.get_window_extent().transformed(
            size)
        # The bbox does not include the axis so manually scale it up so it does
        new_extent = extent.from_extents(
            [[0, 0], [extent.xmax*1.05, extent.ymax*1.05]])
        # Save the clipped region of the figure
        self.figure.savefig(selected_file, bbox_inches=new_extent)

    def update_azimuthal_plot_overlays(self):
        if self.mode != ViewType.polar:
            # Nothing to do. Just return.
            return

        self.clear_azimuthal_overlay_artists()

        # Apply new, visible overlays
        tth, sum = HexrdConfig().last_unscaled_azimuthal_integral_data
        for overlay in HexrdConfig().azimuthal_overlays:
            if not overlay['visible']:
                continue

            material = HexrdConfig().materials[overlay['material']]
            density = round(material.unitcell.density, 2)
            material.compute_powder_overlay(tth, fwhm=overlay['fwhm'],
                                            scale=overlay['scale'])
            result = material.powder_overlay
            # Plot the result so that the plot scales correctly with the data
            # since the fill artist is not taken into account for rescaling.
            line, = self.azimuthal_integral_axis.plot(tth, result, lw=0)
            fill = self.azimuthal_integral_axis.fill_between(
                tth,
                result,
                color=overlay['color'],
                alpha=overlay['opacity']
            )
            fill.set_label(f'{overlay["name"]}({density}g/cm³)')
            self.azimuthal_overlay_artists.append({
                'name': overlay['name'],
                'material': overlay['material'],
                'artists': {
                    'fill': fill,
                    'line': line,
                },
            })
        if (HexrdConfig().show_azimuthal_legend and
                len(self.azimuthal_overlay_artists)):
            self.azimuthal_integral_axis.legend()
        elif (axis := self.azimuthal_integral_axis) and axis.get_legend():
            # Only remove the legend if the axis exists and it has a legend
            axis.get_legend().remove()
        self.draw_idle()

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

        # Apply any selected overlays
        self.update_azimuthal_plot_overlays()

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
        if xys is None or self.iviewer is None:
            return

        for det_key, panel in self.iviewer.instr.detectors.items():
            axis = self.detector_axis(det_key)
            if axis is None:
                # Probably, we are in tabbed view, and this is not the
                # right canvas for this detector...
                continue

            transform_func = transform_from_plain_cartesian_func(self.mode)
            rijs = transform_func(xys[det_key], panel, self.iviewer)

            if self.mode == ViewType.polar:
                rijs = apply_tth_distortion_if_needed(rijs, in_degrees=True)

            artist, = axis.plot(rijs[:, 0], rijs[:, 1], 'm+')
            self.auto_picked_data_artists.append(artist)

    def on_detector_transforms_modified(self, detectors):
        if HexrdConfig().loading_state:
            # Skip the request if we are loading state
            return

        if self.mode is None:
            return

        self.iviewer.update_detectors(detectors)

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

        self.axes_images[0].set_data(self.scaled_display_images[0])
        if self.mode == ViewType.cartesian:
            old_extent = self.axes_images[0].get_extent()
            new_extent = self.iviewer.extent
            # If the extents have changed, that means the detector was
            # interactively moved out of bounds, and we need to relimit.
            if not np.allclose(old_extent, new_extent):
                self.axes_images[0].set_extent(new_extent)
                self.axis.set_xlim(new_extent[:2])
                self.axis.set_ylim(new_extent[2:])
                # Need to update overlays as well. They wouldn't have been
                # drawn in the expanded region yet.
                HexrdConfig().flag_overlay_updates_for_all_materials()
                self.update_overlays()

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
            img = self.iviewer.raw_img.data

            no_nan_methods = [utils.SnipAlgorithmType.Fast_SNIP_1D]
            if HexrdConfig().polar_snip1d_algorithm not in no_nan_methods:
                img[self.iviewer.raw_mask] = np.nan

            background = utils.run_snip1d(img)

        self._snip_viewer_dialog = SnipViewerDialog(background, extent)
        self._snip_viewer_dialog.show()

    def update_mask_boundaries(self, axis):
        # Update is a clear followed by a draw
        self.clear_mask_boundaries()
        self.draw_mask_boundaries(axis)

    def clear_mask_boundaries(self):
        for artist in self._mask_boundary_artists:
            artist.remove()

        self._mask_boundary_artists.clear()

    def draw_mask_boundaries(self, axis, det=None):
        # Create an instrument once that we will re-use
        instr = create_view_hedm_instrument()
        all_verts = []
        for name in MaskManager().visible_boundaries:
            mask = MaskManager().masks[name]
            if self.mode == ViewType.raw:
                if HexrdConfig().stitch_raw_roi_images:
                    # Find masks to keep
                    dets_to_keep = self.iviewer.roi_info['groups'][det]
                    masks_to_keep = []
                    for k, v in mask.data:
                        if k in dets_to_keep:
                            masks_to_keep.append((k, v))

                    # Convert the vertices to their stitched versions.
                    verts = []
                    for k, v in masks_to_keep:
                        ij, _ = self.iviewer.raw_to_stitched(v[:, [1, 0]], k)
                        verts.append(ij[:, [1, 0]])
                else:
                    verts = [v for k, v in mask.data if k == det]
            elif self.mode == ViewType.polar or self.mode == ViewType.stereo:
                verts = create_polar_line_data_from_raw(instr, mask.data)
                if self.mode == ViewType.stereo:
                    # Now convert from polar to stereo
                    for i, vert in enumerate(verts):
                        verts[i] = angles_to_stereo(
                            np.radians(vert),
                            self.iviewer.instr_pv,
                            HexrdConfig().stereo_size,
                        )

            if not verts:
                continue

            # Add nans so they split up in their drawing
            all_verts.append(np.vstack(
                [np.vstack((x, (np.nan, np.nan))) for x in verts]
            ))

        if not all_verts:
            return

        kwargs = {
            'lw': 1,
            'linestyle': '--',
            'color': MaskManager().boundary_color
        }
        self._mask_boundary_artists += axis.plot(
            *np.vstack(all_verts).T,
            **kwargs,
        )


class PolarXAxisTickLocator(AutoLocator):
    """Subclass the tick locator so we can modify its behavior

    We will modify any value ranges provided so that the current x-axis type
    provides nice looking ticks.

    For instance, for Q, we want to see `1, 2, 3, 4, ...`.
    """
    def __init__(self, canvas, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hexrdgui_canvas = canvas

    def tick_values(self, vmin, vmax):
        canvas = self._hexrdgui_canvas
        # Convert to our current x type
        vmin, vmax = canvas.polar_tth_to_x_type([vmin, vmax])
        # Get the tick values for our x type range
        values = super().tick_values(vmin, vmax)
        # Convert back to tth
        return canvas.polar_x_type_to_tth(values)


class PolarXAxisFormatter(FuncFormatter):
    """Subclass the func formatter so we can keep the default formatter in sync

    If any settings are modified on the func formatter, modify the settings on
    the default formatter as well.
    """
    def __init__(self, default_formatter, func):
        super().__init__(func)
        self.default_formatter = default_formatter

    def set_locs(self, *args, **kwargs):
        # Make sure the default formatter is updated as well
        self.default_formatter.set_locs(*args, **kwargs)
        super().set_locs(*args, **kwargs)


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
