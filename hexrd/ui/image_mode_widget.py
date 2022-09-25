from functools import partial
import multiprocessing
import numpy as np

from PySide2.QtCore import QObject, QTimer, Signal

from hexrd.ui.constants import ViewType
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.create_raw_mask import apply_threshold_mask
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import Overlay
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


class ImageModeWidget(QObject):

    # Using string argument instead of ViewType to workaround segfault on
    # conda/macos
    tab_changed = Signal(str)

    # Tell the image canvas to show the snip1d
    polar_show_snip1d = Signal()

    # Mask has been applied
    mask_applied = Signal()

    def __init__(self, parent=None):
        super(ImageModeWidget, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('image_mode_widget.ui', parent)

        # Always start with raw tab
        self.ui.tab_widget.setCurrentIndex(0)

        self.setup_connections()
        self.update_gui_from_config()

    def setup_connections(self):
        self.ui.raw_tabbed_view.toggled.connect(HexrdConfig().set_tab_images)
        self.ui.raw_show_saturation.toggled.connect(
            HexrdConfig().set_show_saturation_level)
        self.ui.raw_threshold_mask.toggled.connect(self.raw_masking)
        self.ui.raw_threshold_mask.toggled.connect(
            HexrdConfig().set_threshold_mask_status)
        self.ui.raw_threshold_comparison.currentIndexChanged.connect(
            HexrdConfig().set_threshold_comparison)
        self.ui.raw_threshold_comparison.currentIndexChanged.connect(
            self.update_mask)
        self.ui.raw_threshold_value.valueChanged.connect(
            HexrdConfig().set_threshold_value)
        self.ui.raw_threshold_value.valueChanged.connect(
            self.update_mask)
        self.ui.cartesian_pixel_size.valueChanged.connect(
            HexrdConfig()._set_cartesian_pixel_size)
        self.ui.cartesian_virtual_plane_distance.valueChanged.connect(
            HexrdConfig().set_cartesian_virtual_plane_distance)
        self.ui.cartesian_plane_normal_rotate_x.valueChanged.connect(
            HexrdConfig().set_cartesian_plane_normal_rotate_x)
        self.ui.cartesian_plane_normal_rotate_y.valueChanged.connect(
            HexrdConfig().set_cartesian_plane_normal_rotate_y)
        self.ui.polar_pixel_size_tth.valueChanged.connect(
            HexrdConfig()._set_polar_pixel_size_tth)
        self.ui.polar_pixel_size_eta.valueChanged.connect(
            HexrdConfig()._set_polar_pixel_size_eta)
        self.ui.polar_res_tth_min.valueChanged.connect(
            HexrdConfig().set_polar_res_tth_min)
        self.ui.polar_res_tth_max.valueChanged.connect(
            HexrdConfig().set_polar_res_tth_max)
        self.ui.polar_res_eta_min.valueChanged.connect(
            self.on_eta_min_changed)
        self.ui.polar_res_eta_max.valueChanged.connect(
            self.on_eta_max_changed)
        self.ui.polar_apply_snip1d.toggled.connect(self.update_enable_states)
        self.ui.polar_apply_snip1d.toggled.connect(
            HexrdConfig().set_polar_apply_snip1d)
        self.ui.polar_snip1d_algorithm.currentIndexChanged.connect(
            HexrdConfig().set_polar_snip1d_algorithm)
        self.ui.polar_snip1d_width.valueChanged.connect(
            HexrdConfig().set_polar_snip1d_width)
        self.ui.polar_snip1d_numiter.valueChanged.connect(
            HexrdConfig().set_polar_snip1d_numiter)
        self.ui.polar_apply_erosion.toggled.connect(
            HexrdConfig().set_polar_apply_erosion)
        HexrdConfig().instrument_config_loaded.connect(
            self.auto_generate_cartesian_params)
        HexrdConfig().instrument_config_loaded.connect(
            self.auto_generate_polar_params)

        self.ui.polar_show_snip1d.clicked.connect(self.polar_show_snip1d.emit)

        self.ui.tab_widget.currentChanged.connect(self.currentChanged)

        HexrdConfig().mgr_threshold_mask_changed.connect(
            self.ui.raw_threshold_mask.setChecked)

        HexrdConfig().state_loaded.connect(self.update_gui_from_config)

        HexrdConfig().overlay_distortions_modified.connect(
            self.overlay_distortions_modified)
        HexrdConfig().overlay_renamed.connect(
            self.update_polar_tth_distortion_overlay_options)
        HexrdConfig().overlay_list_modified.connect(
            self.update_polar_tth_distortion_overlay_options)

        self.ui.polar_apply_tth_distortion.toggled.connect(
            self.polar_tth_distortion_overlay_changed)
        self.ui.polar_tth_distortion_overlay.currentIndexChanged.connect(
            self.polar_tth_distortion_overlay_changed)

    def currentChanged(self, index):
        modes = {
            0: ViewType.raw,
            1: ViewType.cartesian,
            2: ViewType.polar
        }
        ind = self.ui.tab_widget.currentIndex()
        self.tab_changed.emit(modes[ind])

    def all_widgets(self):
        widgets = [
            self.ui.raw_tabbed_view,
            self.ui.raw_show_saturation,
            self.ui.raw_threshold_mask,
            self.ui.raw_threshold_comparison,
            self.ui.raw_threshold_value,
            self.ui.cartesian_pixel_size,
            self.ui.cartesian_virtual_plane_distance,
            self.ui.cartesian_plane_normal_rotate_x,
            self.ui.cartesian_plane_normal_rotate_y,
            self.ui.polar_pixel_size_tth,
            self.ui.polar_pixel_size_eta,
            self.ui.polar_res_tth_min,
            self.ui.polar_res_tth_max,
            self.ui.polar_res_eta_min,
            self.ui.polar_res_eta_max,
            self.ui.polar_apply_snip1d,
            self.ui.polar_snip1d_algorithm,
            self.ui.polar_snip1d_width,
            self.ui.polar_snip1d_numiter,
            self.ui.polar_show_snip1d,
            self.ui.polar_apply_erosion,
            self.ui.polar_apply_tth_distortion,
            self.ui.polar_tth_distortion_overlay,
        ]

        return widgets

    def update_gui_from_config(self):
        with block_signals(*self.all_widgets()):
            self.ui.raw_threshold_comparison.setCurrentIndex(
                HexrdConfig().threshold_comparison)
            self.ui.raw_threshold_value.setValue(
                HexrdConfig().threshold_value)
            self.ui.raw_threshold_mask.setChecked(
                HexrdConfig().threshold_mask_status)
            self.ui.cartesian_pixel_size.setValue(
                HexrdConfig().cartesian_pixel_size)
            self.ui.cartesian_virtual_plane_distance.setValue(
                HexrdConfig().cartesian_virtual_plane_distance)
            self.ui.cartesian_plane_normal_rotate_x.setValue(
                HexrdConfig().cartesian_plane_normal_rotate_x)
            self.ui.cartesian_plane_normal_rotate_y.setValue(
                HexrdConfig().cartesian_plane_normal_rotate_y)
            self.ui.polar_pixel_size_tth.setValue(
                HexrdConfig().polar_pixel_size_tth)
            self.ui.polar_pixel_size_eta.setValue(
                HexrdConfig().polar_pixel_size_eta)
            self.ui.polar_res_tth_min.setValue(
                HexrdConfig().polar_res_tth_min)
            self.ui.polar_res_tth_max.setValue(
                HexrdConfig().polar_res_tth_max)
            self.ui.polar_res_eta_min.setValue(
                HexrdConfig().polar_res_eta_min)
            self.ui.polar_res_eta_max.setValue(
                HexrdConfig().polar_res_eta_max)
            self.ui.polar_snip1d_algorithm.setCurrentIndex(
                HexrdConfig().polar_snip1d_algorithm)
            self.ui.polar_apply_snip1d.setChecked(
                HexrdConfig().polar_apply_snip1d)
            self.ui.polar_snip1d_width.setValue(
                HexrdConfig().polar_snip1d_width)
            self.ui.polar_snip1d_numiter.setValue(
                HexrdConfig().polar_snip1d_numiter)
            self.ui.polar_apply_erosion.setChecked(
                HexrdConfig().polar_apply_erosion)

            self.update_polar_tth_distortion_overlay_options()
            self.update_enable_states()

    def update_enable_states(self):
        apply_snip1d = self.ui.polar_apply_snip1d.isChecked()
        self.ui.polar_snip1d_width.setEnabled(apply_snip1d)
        self.ui.polar_snip1d_numiter.setEnabled(apply_snip1d)
        self.ui.polar_apply_erosion.setEnabled(apply_snip1d)

    def auto_generate_cartesian_params(self):
        if HexrdConfig().loading_state:
            # Don't modify the parameters if a state file is being
            # loaded. We want to keep whatever is in the state file...
            return

        # This will automatically generate and set values for the
        # Cartesian pixel size and virtual plane distance based upon
        # values in the instrument config.
        # This function does not invoke a re-render.
        detectors = list(HexrdConfig().detectors.values())
        distances = [
            x['transform']['translation']['value'][2] for x in detectors
        ]
        sizes = [x['pixels']['size']['value'] for x in detectors]

        average_dist = sum(distances) / len(distances)
        average_size = sum([x[0] + x[1] for x in sizes]) / (2 * len(sizes))

        cart_config = HexrdConfig().config['image']['cartesian']
        cart_config['pixel_size'] = average_size * 5
        cart_config['virtual_plane_distance'] = abs(average_dist)

        # Get the GUI to update with the new values
        self.update_gui_from_config()

    def auto_generate_polar_params(self):
        if HexrdConfig().loading_state:
            # Don't modify the parameters if a state file is being
            # loaded. We want to keep whatever is in the state file...
            return

        # This will automatically generate and set values for the polar
        # pixel values based upon the config.
        # This function does not invoke a re-render.
        manager = multiprocessing.Manager()
        keys = ['max_tth_ps', 'max_eta_ps', 'min_tth', 'max_tth']
        results = {key: manager.list() for key in keys}

        f = partial(compute_polar_params, **results)
        instr = create_hedm_instrument()
        with multiprocessing.Pool() as pool:
            pool.map(f, instr.detectors.values())

        # Set these manually so no rerender signals are fired
        params = {
            'pixel_size_tth': max(results['max_tth_ps']),
            'pixel_size_eta': max(results['max_eta_ps']),
            'tth_min': min(results['min_tth']),
            'tth_max': max(results['max_tth'])
        }

        # Sometimes, this is too big. Bring it down if it is.
        px_eta = params['pixel_size_eta']
        params['pixel_size_eta'] = px_eta if px_eta < 90 else 5

        HexrdConfig().config['image']['polar'].update(params)

        # Update all of the materials with the new tth_max
        HexrdConfig().reset_tth_max_all_materials()

        # Get the GUI to update with the new values
        self.update_gui_from_config()

    def raw_masking(self, checked):
        # Toggle threshold masking on or off
        # Creates a copy of the ImageSeries dict so that the images can
        # easily be reverted to their original state if the mask is
        # toggled off.
        self.ui.raw_threshold_comparison.setEnabled(checked)
        self.ui.raw_threshold_comparison.setCurrentIndex(
            HexrdConfig().threshold_comparison)
        self.ui.raw_threshold_value.setEnabled(checked)
        self.ui.raw_threshold_value.setValue(HexrdConfig().threshold_value)
        self.update_mask(checked)

    def update_mask(self, masking):
        # Add or remove the mask. This will cause a re-render
        if not isinstance(masking, bool) or masking:
            apply_threshold_mask()
        self.mask_applied.emit()

    def reset_masking(self, checked=False):
        self.ui.raw_threshold_mask.setChecked(checked)

    @property
    def polar_apply_tth_distortion(self):
        return self.ui.polar_apply_tth_distortion.isChecked()

    @polar_apply_tth_distortion.setter
    def polar_apply_tth_distortion(self, b):
        self.ui.polar_apply_tth_distortion.setChecked(b)
        self.ui.polar_tth_distortion_overlay.setEnabled(b)

    @property
    def polar_tth_distortion_overlay(self):
        if (not self.polar_apply_tth_distortion or
                self.ui.polar_tth_distortion_overlay.currentIndex() == -1):
            return None

        return self.ui.polar_tth_distortion_overlay.currentText()

    @polar_tth_distortion_overlay.setter
    def polar_tth_distortion_overlay(self, name):
        if isinstance(name, Overlay):
            # Grab the name.
            name = name.name

        w = self.ui.polar_tth_distortion_overlay
        options = [w.itemText(i) for i in range(w.count())]
        enabled = name in options
        self.polar_apply_tth_distortion = enabled
        if enabled:
            w.setCurrentText(name)

    def overlay_distortions_modified(self, name):
        if name == self.polar_tth_distortion_overlay:
            # We need to rerender the whole polar view
            HexrdConfig().flag_overlay_updates_for_all_materials()
            # Give the overlays a second to finish updating before we rerender
            QTimer.singleShot(0, lambda: HexrdConfig().rerender_needed.emit())

        # Need to update the names
        self.update_polar_tth_distortion_overlay_options()

    def update_polar_tth_distortion_overlay_options(self):
        w = self.ui.polar_tth_distortion_overlay
        prev_text = w.currentText()
        with block_signals(w):
            w.clear()
            names = []
            for overlay in HexrdConfig().overlays:
                if overlay.is_powder and overlay.has_tth_distortion:
                    names.append(overlay.name)

            w.addItems(names)

            current = HexrdConfig().polar_tth_distortion_overlay
            if current and current.name in names:
                w.setCurrentText(current.name)
                self.polar_apply_tth_distortion = True
            elif prev_text in names:
                # Keep the previous one saved, even if there is no
                # distortion. This is so that we can toggle on/off and
                # keep the same one selected.
                w.setCurrentText(prev_text)

            if self.polar_apply_tth_distortion:
                # Make sure any changes get saved to the config
                self.polar_tth_distortion_overlay_changed()

        enable = w.count() != 0
        self.ui.polar_apply_tth_distortion.setEnabled(enable)
        if not enable:
            self.polar_apply_tth_distortion = False

    def polar_tth_distortion_overlay_changed(self):
        HexrdConfig().polar_tth_distortion_overlay = (
            self.polar_tth_distortion_overlay)

    def on_eta_min_changed(self, min_value):
        """Sync max when min is changed."""
        max_value = HexrdConfig().polar_res_eta_max
        update_max = False
        if min_value > max_value:
            max_value = min_value
            update_max = True
        elif max_value - min_value > 360.0:
            max_value = min_value + 360.0
            update_max = True
        if update_max:
            with block_signals(self.ui.polar_res_eta_max):
                self.ui.polar_res_eta_max.setValue(max_value)
                HexrdConfig().set_polar_res_eta_max(max_value, rerender=False)
        HexrdConfig().polar_res_eta_min = min_value

    def on_eta_max_changed(self, max_value):
        """Sync min when max is changed."""
        min_value = HexrdConfig().polar_res_eta_min
        update_min = False
        if max_value < min_value:
            min_value = max_value
            update_min = True
        elif max_value - min_value > 360.0:
            min_value = max_value - 360.0
            update_min = True
        if update_min:
            with block_signals(self.ui.polar_res_eta_min):
                self.ui.polar_res_eta_min.setValue(min_value)
                HexrdConfig().set_polar_res_eta_min(min_value, rerender=False)
        HexrdConfig().polar_res_eta_max = max_value


def compute_polar_params(panel, max_tth_ps, max_eta_ps, min_tth, max_tth):
    # Other than panel, all arguments are lists for appending results
    # pixel sizes
    #
    # FIXME: currently ignoring any non-trivial tvec set on instrument!
    #        This would get set via the `origin` kwarg
    max_tth_ps.append(
        np.power(
            10,
            np.round(
                np.log10(
                    10*np.degrees(
                        np.median(panel.pixel_tth_gradient())
                    )
                )
            )
        )
    )
    max_eta_ps.append(
        np.power(
            10,
            np.round(
                np.log10(
                    10*np.degrees(
                        np.median(panel.pixel_eta_gradient())
                    )
                )
            )
        )
    )

    # tth ranges
    ptth, peta = panel.pixel_angles()
    min_tth.append(np.degrees(np.min(ptth)))
    max_tth.append(np.degrees(np.max(ptth)))
