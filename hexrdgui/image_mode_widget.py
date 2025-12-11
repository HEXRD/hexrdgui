from functools import partial
import multiprocessing
import numpy as np

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from hexrd.imageseries import ImageSeries

from hexrdgui.azimuthal_overlay_manager import AzimuthalOverlayManager
from hexrdgui.constants import PolarXAxisType, ViewType
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_load_manager import ImageLoadManager
from hexrdgui.select_items_dialog import SelectItemsDialog
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals

TAB_INDEX_TO_VIEW_MODE = {
    0: ViewType.raw,
    1: ViewType.cartesian,
    2: ViewType.polar,
    3: ViewType.stereo,
}
VIEW_MODE_TO_TAB_INDEX = {v: k for k, v in TAB_INDEX_TO_VIEW_MODE.items()}


class ImageModeWidget(QObject):

    # Using string argument instead of ViewType to workaround segfault on
    # conda/macos
    tab_changed = Signal(str)

    # Tell the image canvas to show the snip1d
    polar_show_snip1d = Signal()

    # Tell the image canvas to create a waterfall plot
    create_waterfall_plot = Signal()

    raw_show_zoom_dialog = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('image_mode_widget.ui', parent)

        # Always start with raw tab
        self.ui.tab_widget.setCurrentIndex(0)

        # Don't allow negative distances
        self.ui.cartesian_virtual_plane_distance.setMinimum(1e-8)

        # Hide stereo_project_from_polar for now, as projecting from polar
        # appears to give a better image (lines up better with overlays)
        # than projecting from raw.
        # FIXME: why is projecting from raw different?
        self.ui.stereo_project_from_polar.setVisible(False)

        self.setup_eiger_stream_v2_options()
        self.setup_connections()
        self.update_gui_from_config()

    def setup_connections(self):
        self.ui.installEventFilter(self)
        self.ui.raw_tabbed_view.toggled.connect(HexrdConfig().set_tab_images)
        self.ui.raw_show_saturation.toggled.connect(
            HexrdConfig().set_show_saturation_level)
        self.ui.raw_stitch_roi_images.toggled.connect(
            HexrdConfig().set_stitch_raw_roi_images)
        self.ui.raw_show_zoom_dialog.clicked.connect(
            self.raw_show_zoom_dialog)
        self.ui.eiger_stream_v2_setting.currentIndexChanged.connect(
            self.on_eiger_stream_v2_settings_modified)
        self.ui.eiger_stream_v2_multiplier.valueChanged.connect(
            self.on_eiger_stream_v2_settings_modified)
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
        self.ui.polar_apply_scaling_to_lineout.toggled.connect(
            HexrdConfig().set_polar_apply_scaling_to_lineout)
        self.ui.polar_x_axis_type.currentTextChanged.connect(
            self.on_polar_x_axis_type_changed)
        self.ui.polar_active_beam.currentIndexChanged.connect(
            self.on_active_beam_changed)
        self.ui.create_waterfall_plot.clicked.connect(
            self.on_create_waterfall_plot_clicked)
        self.ui.select_detectors_for_lineout.clicked.connect(
            self.on_select_detectors_for_lineout_clicked)

        HexrdConfig().instrument_config_loaded.connect(
            self.on_instrument_config_load)
        HexrdConfig().active_beam_switched.connect(
            # We might need to update the eta range as well (for TARDIS),
            # so just update everything.
            self.update_gui_from_config)

        HexrdConfig().enable_image_mode_widget.connect(
            self.enable_image_mode_widget)
        HexrdConfig().set_image_mode_widget_tab.connect(
            self.set_image_mode_widget_tab)

        self.ui.polar_show_snip1d.clicked.connect(self.polar_show_snip1d.emit)

        self.ui.tab_widget.currentChanged.connect(self.currentChanged)

        self.ui.polar_azimuthal_overlays.pressed.connect(
            self.show_polar_overlay_manager)
        self.ui.azimuthal_offset.valueChanged.connect(
            self.update_azimuthal_offset)

        HexrdConfig().state_loaded.connect(self.update_gui_from_config)

        HexrdConfig().overlay_distortions_modified.connect(
            self.overlay_distortions_modified)
        HexrdConfig().overlay_renamed.connect(
            self.update_polar_tth_distortion_overlay_options)
        HexrdConfig().overlay_list_modified.connect(
            self.update_polar_tth_distortion_overlay_options)
        HexrdConfig().polar_tth_distortion_overlay_changed.connect(
            self.on_polar_tth_distortion_overlay_changed)

        self.ui.polar_apply_tth_distortion.toggled.connect(
            self.polar_tth_distortion_overlay_changed)
        self.ui.polar_tth_distortion_overlay.currentIndexChanged.connect(
            self.polar_tth_distortion_overlay_changed)

        self.ui.stereo_size.valueChanged.connect(HexrdConfig().set_stereo_size)
        self.ui.stereo_show_border.toggled.connect(
            HexrdConfig().set_stereo_show_border)
        self.ui.stereo_project_from_polar.toggled.connect(
            HexrdConfig().set_stereo_project_from_polar)

        ImageLoadManager().new_images_loaded.connect(
            self.on_new_images_loaded)

    def setup_eiger_stream_v2_options(self):
        combo = self.ui.eiger_stream_v2_setting
        combo.clear()

        options = {
            'Threshold 1': 'threshold_1',
            'Threshold 2': 'threshold_2',
            'Difference': 'man_diff',
        }
        for k, v in options.items():
            combo.addItem(k, v)

    def on_new_images_loaded(self):
        self.update_visibility_states()
        self.update_eiger_stream_v2_settings()

    def update_eiger_stream_v2_settings(self):
        ims_dict = HexrdConfig().imageseries_dict

        # We assume that all imageseries have the same options set
        visible = False
        if ims_dict:
            ims = next(iter(ims_dict.values()))
            visible = _is_eiger_stream_v2(ims)

        self.ui.eiger_stream_v2_group.setVisible(visible)

        if not visible:
            # Nothing else to do
            return

        settings = ims.option_values()
        w = self.ui.eiger_stream_v2_setting
        idx = w.findData(settings['threshold_setting'])
        if idx != -1:
            with block_signals(w):
                w.setCurrentIndex(idx)

        mult_enabled = w.currentData() == 'man_diff'
        mult_widgets = [
            self.ui.eiger_stream_v2_multiplier_label,
            self.ui.eiger_stream_v2_multiplier,
        ]
        for w in mult_widgets:
            w.setEnabled(mult_enabled)

        w = self.ui.eiger_stream_v2_multiplier
        with block_signals(w):
            w.setValue(settings['multiplier'])

    def on_eiger_stream_v2_settings_modified(self):
        ims_dict = HexrdConfig().imageseries_dict

        if (
            not ims_dict or
            not _is_eiger_stream_v2(next(iter(ims_dict.values())))
        ):
            # This shouldn't have been triggered. Let's ignore it.
            self.update_eiger_stream_v2_settings()
            return

        settings = {
            'threshold_setting': self.ui.eiger_stream_v2_setting.currentData(),
            'multiplier': self.ui.eiger_stream_v2_multiplier.value(),
        }

        for ims in ims_dict.values():
            for k, v in settings.items():
                ims.set_option(k, v)

        # Trigger all the same logic as if we loaded new images
        ImageLoadManager().new_images_loaded.emit()

    def eventFilter(self, target, event):
        if target is self.ui and event.type() == QEvent.Resize:
            size = self.ui.polar_scroll_area_contents.minimumSizeHint()

            # Make the minimum height of the polar scroll area to be
            # either its size hint or half the display height, whichever
            # is smaller.
            display_height = QApplication.primaryScreen().geometry().height()
            size.setHeight(min(size.height(), int(display_height * 0.5)))

            # Don't allow the polar scroll area to get resized below
            # its minimum width, because we don't allow horizontal
            # scrolling.
            # Include the vertical bar width in this minimum width
            vert_bar = self.ui.polar_scroll_area.verticalScrollBar()
            size.setWidth(size.width() + vert_bar.sizeHint().width())
            self.ui.setMinimumSize(size)

        return False

    def enable_image_mode_widget(self, b):
        self.ui.tab_widget.setEnabled(b)

    def set_image_mode_widget_tab(self, view_mode):
        tab = VIEW_MODE_TO_TAB_INDEX[view_mode]
        self.ui.tab_widget.setCurrentIndex(tab)

    def currentChanged(self, index):
        view_mode = TAB_INDEX_TO_VIEW_MODE[index]
        self.tab_changed.emit(view_mode)

    def all_widgets(self):
        widgets = [
            self.ui.raw_tabbed_view,
            self.ui.raw_show_saturation,
            self.ui.raw_stitch_roi_images,
            self.ui.raw_show_zoom_dialog,
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
            self.ui.polar_apply_scaling_to_lineout,
            self.ui.polar_x_axis_type,
            self.ui.polar_active_beam,
            self.ui.stereo_size,
            self.ui.stereo_show_border,
            self.ui.stereo_project_from_polar,
        ]

        return widgets

    def update_gui_from_config(self):
        with block_signals(*self.all_widgets()):
            self.ui.raw_stitch_roi_images.setChecked(
                HexrdConfig().stitch_raw_roi_images)
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
            self.ui.polar_apply_scaling_to_lineout.setChecked(
                HexrdConfig().polar_apply_scaling_to_lineout)
            self.polar_x_axis_type = HexrdConfig().polar_x_axis_type
            self.ui.polar_active_beam.setCurrentText(
                HexrdConfig().active_beam_name)
            self.ui.stereo_size.setValue(HexrdConfig().stereo_size)
            self.ui.stereo_show_border.setChecked(
                HexrdConfig().stereo_show_border)
            self.ui.stereo_project_from_polar.setChecked(
                HexrdConfig().stereo_project_from_polar)

            self.update_polar_tth_distortion_overlay_options()
            self.update_enable_states()

        self.update_visibility_states()
        self.update_eiger_stream_v2_settings()

    def update_enable_states(self):
        apply_snip1d = self.ui.polar_apply_snip1d.isChecked()
        self.ui.polar_snip1d_width.setEnabled(apply_snip1d)
        self.ui.polar_snip1d_numiter.setEnabled(apply_snip1d)
        self.ui.polar_apply_erosion.setEnabled(apply_snip1d)

    def on_instrument_config_load(self):
        self.update_visibility_states()
        self.update_beam_names()
        self.auto_generate_cartesian_params()
        self.auto_generate_polar_params()

    def update_visibility_states(self):
        has_roi = HexrdConfig().instrument_has_roi
        self.ui.raw_stitch_roi_images.setVisible(has_roi)

        has_multi_xrs = HexrdConfig().has_multi_xrs
        self.ui.polar_active_beam.setVisible(has_multi_xrs)
        self.ui.polar_active_beam_label.setVisible(has_multi_xrs)

        # We can only make a waterfall plot if there is more than one
        # frame in the imageseries.
        # If there are more than 20, that's too many, and let's just ignore
        # it as well. All of the cases we know of currently should have
        # no more than 15 frames in the imageseries.
        can_make_waterfall_plot = (
            1 < HexrdConfig().imageseries_length <= 20
        )
        self.ui.create_waterfall_plot.setVisible(can_make_waterfall_plot)

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
            x['transform']['translation'][2] for x in detectors
        ]
        sizes = [x['pixels']['size'] for x in detectors]

        average_dist = sum(distances) / len(distances)
        average_size = sum([x[0] + x[1] for x in sizes]) / (2 * len(sizes))

        cart_config = HexrdConfig().config['image']['cartesian']

        # Round these to two for a nicer display
        cart_config['pixel_size'] = round(average_size, 2)
        cart_config['virtual_plane_distance'] = round(abs(average_dist), 2)

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

        # Round these to two decimal places for a nicer display
        for k, v in params.items():
            params[k] = round(v, 2)

        HexrdConfig().config['image']['polar'].update(params)

        # Update all of the materials with the new tth_max
        HexrdConfig().reset_tth_max_all_materials()

        # Get the GUI to update with the new values
        self.update_gui_from_config()

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
        if name and not isinstance(name, str):
            # Grab the name.
            name = name.name

        w = self.ui.polar_tth_distortion_overlay
        options = [w.itemText(i) for i in range(w.count())]
        enabled = name in options
        self.polar_apply_tth_distortion = enabled
        if enabled:
            w.setCurrentText(name)

    def on_polar_tth_distortion_overlay_changed(self):
        self.polar_tth_distortion_overlay = (
            HexrdConfig().polar_tth_distortion_object
        )

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

            if obj := HexrdConfig().saved_custom_polar_tth_distortion_object:
                names.append(obj.name)

            w.addItems(names)

            current = HexrdConfig().polar_tth_distortion_object
            if current and current.name in names:
                w.setCurrentText(current.name)
                self.polar_apply_tth_distortion = True
            else:
                self.polar_apply_tth_distortion = current is not None
                if prev_text in names:
                    # Keep the previous one saved, even if there is no
                    # distortion. This is so that we can toggle on/off and
                    # keep the same one selected.
                    w.setCurrentText(prev_text)

            if self.polar_apply_tth_distortion:
                # Make sure any changes get saved to the config
                self.polar_tth_distortion_overlay_changed()

        enable = w.count() != 0
        self.ui.polar_apply_tth_distortion.setEnabled(enable)

    def polar_tth_distortion_overlay_changed(self):
        obj = self.polar_tth_distortion_overlay
        if obj == '[Custom]':
            obj = HexrdConfig().saved_custom_polar_tth_distortion_object

        HexrdConfig().polar_tth_distortion_object = obj

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

    @property
    def polar_x_axis_type(self):
        label = self.ui.polar_x_axis_type.currentText()
        return POLAR_X_AXIS_LABELS_TO_VALUES[label]

    @polar_x_axis_type.setter
    def polar_x_axis_type(self, value):
        label = POLAR_X_AXIS_VALUES_TO_LABELS[value]
        self.ui.polar_x_axis_type.setCurrentText(label)

    def on_polar_x_axis_type_changed(self):
        HexrdConfig().polar_x_axis_type = self.polar_x_axis_type

    def show_polar_overlay_manager(self):
        if hasattr(self, '_polar_overlay_manager'):
            self._polar_overlay_manager.ui.reject()
            del self._polar_overlay_manager

        self._polar_overlay_manager = AzimuthalOverlayManager(self.ui)
        self._polar_overlay_manager.show()

    def update_azimuthal_offset(self, value):
        HexrdConfig().azimuthal_offset = value
        HexrdConfig().azimuthal_options_modified.emit()

    def update_beam_names(self):
        with block_signals(self.ui.polar_active_beam):
            self.ui.polar_active_beam.clear()
            self.ui.polar_active_beam.addItems(HexrdConfig().beam_names)
            self.ui.polar_active_beam.setCurrentText(
                HexrdConfig().active_beam_name)

    def on_active_beam_changed(self):
        HexrdConfig().active_beam_name = self.ui.polar_active_beam.currentText()

    def on_create_waterfall_plot_clicked(self):
        self.create_waterfall_plot.emit()

    def on_select_detectors_for_lineout_clicked(self):
        detector_names = HexrdConfig().detector_names
        selected = HexrdConfig().azimuthal_lineout_detectors
        if selected is None:
            selected = detector_names

        items = [(name, name in selected) for name in detector_names]
        dialog = SelectItemsDialog(
            items,
            'Select Detectors for Lineout',
            self.ui,
        )
        QTimer.singleShot(0, dialog.adjustSize)
        if not dialog.exec():
            return

        HexrdConfig().azimuthal_lineout_detectors = dialog.selected_items


POLAR_X_AXIS_LABELS_TO_VALUES = {
    '2θ': PolarXAxisType.tth,
    'Q': PolarXAxisType.q,
}
POLAR_X_AXIS_VALUES_TO_LABELS = {
    v: k for k, v in POLAR_X_AXIS_LABELS_TO_VALUES.items()
}

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


def _get_ims_format(ims: ImageSeries) -> str | None:
    # If "None" is returned, the format could not be determined

    # We have to recursively "dig" into the imageseries and adapters
    # in order to find the original adapter.
    adapter = ims
    while hasattr(adapter, '_adapter') or hasattr(adapter, '_imser'):
        if hasattr(adapter, '_adapter'):
            adapter = adapter._adapter
        else:
            # ProcessedImageSeries have an '_imser' on them
            adapter = adapter._imser

    return getattr(adapter, 'format', None)


def _is_eiger_stream_v2(ims: ImageSeries) -> bool:
    return _get_ims_format(ims) == 'eiger-stream-v2'
