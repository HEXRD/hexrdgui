import copy
from functools import partial
import multiprocessing
import numpy as np

from PySide2.QtCore import QObject, QSignalBlocker, Signal

from hexrd.ui.constants import UI_RAW, UI_CARTESIAN, UI_POLAR
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.create_raw_mask import apply_raw_mask, remove_raw_mask
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class ImageModeWidget(QObject):

    # The string indicates which tab was selected
    tab_changed = Signal(int)

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
            HexrdConfig().set_threshold_mask)
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
        self.ui.polar_apply_snip1d.toggled.connect(
            HexrdConfig().set_polar_apply_snip1d)
        self.ui.polar_snip1d_width.valueChanged.connect(
            HexrdConfig().set_polar_snip1d_width)
        self.ui.polar_snip1d_numiter.valueChanged.connect(
            HexrdConfig().set_polar_snip1d_numiter)
        HexrdConfig().instrument_config_loaded.connect(
            self.auto_generate_cartesian_params)
        HexrdConfig().instrument_config_loaded.connect(
            self.auto_generate_polar_params)

        self.ui.polar_show_snip1d.clicked.connect(self.polar_show_snip1d.emit)

        self.ui.tab_widget.currentChanged.connect(self.currentChanged)

    def currentChanged(self, index):
        modes = {
            0: UI_RAW,
            1: UI_CARTESIAN,
            2: UI_POLAR
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
            self.ui.polar_apply_snip1d,
            self.ui.polar_snip1d_width,
            self.ui.polar_snip1d_numiter,
            self.ui.polar_show_snip1d
        ]

        return widgets

    def update_gui_from_config(self):
        blocked = [QSignalBlocker(x) for x in self.all_widgets()]  # noqa: F841
        self.ui.raw_threshold_comparison.setCurrentIndex(
            HexrdConfig().threshold_comparison)
        self.ui.raw_threshold_value.setValue(
            HexrdConfig().threshold_value)
        self.ui.raw_threshold_mask.setChecked(
            HexrdConfig().threshold_mask)
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
        self.ui.polar_apply_snip1d.setChecked(
            HexrdConfig().polar_apply_snip1d)
        self.ui.polar_snip1d_width.setValue(
            HexrdConfig().polar_snip1d_width)
        self.ui.polar_snip1d_numiter.setValue(
            HexrdConfig().polar_snip1d_numiter)

    def auto_generate_cartesian_params(self):
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
            'pixel_size_tth': 10 * np.degrees(max(results['max_tth_ps'])),
            'pixel_size_eta': 2 * np.degrees(max(results['max_eta_ps'])),
            'tth_min': np.degrees(min(results['min_tth'])),
            'tth_max': np.degrees(max(results['max_tth']))
        }

        # Sometimes, this is too big. Bring it down if it is.
        px_eta = params['pixel_size_eta']
        params['pixel_size_eta'] = px_eta if px_eta < 90 else 5

        HexrdConfig().config['image']['polar'].update(params)

        # Get the GUI to update with the new values
        self.update_gui_from_config()

    def raw_masking(self, checked):
        # Toggle threshold masking on or off
        # Creates a copy of the ImageSeries dict so that the images can
        # easily be reverted to their original state if the mask is
        # toggled off.
        self.ui.raw_threshold_comparison.setEnabled(checked)
        self.ui.raw_threshold_value.setEnabled(checked)
        if not hasattr(self, 'ims_copy') or self.ims_copy is None:
            self.ims_copy = copy.copy(HexrdConfig().imageseries_dict)
        self.update_mask(checked)

    def update_mask(self, masking):
        # Add or remove the mask. This will cause a re-render
        if not isinstance(masking, bool) or masking:
            apply_raw_mask(self.ims_copy)
        else:
            remove_raw_mask(self.ims_copy)
            self.ims_copy = None
        self.mask_applied.emit()

    def reset_masking(self, checked=False):
        self.ui.raw_threshold_mask.setChecked(checked)


def compute_polar_params(panel, max_tth_ps, max_eta_ps, min_tth, max_tth):
    # Other than panel, all arguments are lists for appending results
    # pixel sizes
    ang_ps = panel.angularPixelSize(
        np.vstack([i.flatten() for i in panel.pixel_coords]).T
    )
    max_tth_ps.append(np.max(ang_ps[:, 0]))
    max_eta_ps.append(np.max(ang_ps[:, 1]))

    # tth ranges
    ptth, peta = panel.pixel_angles()
    min_tth.append(np.min(ptth))
    max_tth.append(np.max(ptth))
