from __future__ import annotations

from functools import partial
import os
from pathlib import Path
import shutil
import tempfile
from collections.abc import Sequence
from typing import Any, TYPE_CHECKING

import h5py
import numpy as np
from skimage import measure

from PySide6.QtCore import QEvent, QObject, Qt, QThreadPool, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from hexrdgui.about_dialog import AboutDialog
from hexrdgui.absorption_correction_options_dialog import (
    AbsorptionCorrectionOptionsDialog,
)
from hexrdgui.async_runner import AsyncRunner
from hexrdgui.beam_marker_style_editor import BeamMarkerStyleEditor
from hexrdgui.calibration_slider_widget import CalibrationSliderWidget
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.color_map_editor import ColorMapEditor
from hexrdgui.config_dialog import ConfigDialog
from hexrdgui.edit_colormap_list_dialog import EditColormapListDialog
from hexrdgui.masking.constants import MaskType
from hexrdgui.masking.mask_manager import MaskManager
from hexrdgui.median_filter_dialog import MedianFilterDialog
from hexrdgui.progress_dialog import ProgressDialog
from hexrdgui.cal_tree_view import CalTreeView
from hexrdgui.masking.hand_drawn_mask_dialog import HandDrawnMaskDialog
from hexrdgui.image_stack_dialog import ImageStackDialog
from hexrdgui.indexing.run import FitGrainsRunner, IndexingRunner
from hexrdgui.indexing.fit_grains_results_dialog import FitGrainsResultsDialog
from hexrdgui.input_dialog import InputDialog
from hexrdgui.instrument_form_view_widget import InstrumentFormViewWidget
from hexrdgui.calibration.calibration_runner import CalibrationRunner
from hexrdgui.calibration.auto.powder_runner import PowderRunner
from hexrdgui.calibration.hedm.calibration_runner import HEDMCalibrationRunner
from hexrdgui.calibration.hkl_picks_tree_view_dialog import (
    HKLPicksTreeViewDialog,
    overlays_to_tree_format,
    tree_format_to_picks,
)
from hexrdgui.calibration.structureless import StructurelessCalibrationRunner
from hexrdgui.calibration.wppf_runner import WppfRunner
from hexrdgui.masking.create_polar_mask import rebuild_polar_masks
from hexrdgui.masking.create_raw_mask import convert_polar_to_raw, rebuild_raw_masks
from hexrdgui.constants import ViewType, DOCUMENTATION_URL
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_calculator_dialog import ImageCalculatorDialog
from hexrdgui.image_file_manager import ImageFileManager
from hexrdgui.image_load_manager import ImageLoadManager
from hexrdgui.llnl_import_tool_dialog import LLNLImportToolDialog
from hexrdgui.load_images_dialog import LoadImagesDialog
from hexrdgui.simple_image_series_dialog import SimpleImageSeriesDialog
from hexrdgui.pinhole_mask_dialog import PinholeMaskDialog
from hexrdgui.pinhole_panel_buffer import generate_pinhole_panel_buffer
from hexrdgui.polarization_options_dialog import PolarizationOptionsDialog
from hexrdgui.masking.mask_manager_dialog import MaskManagerDialog
from hexrdgui.masking.mask_regions_dialog import MaskRegionsDialog
from hexrdgui.materials_panel import MaterialsPanel
from hexrdgui.messages_widget import MessagesWidget
from hexrdgui.save_images_dialog import SaveImagesDialog
from hexrdgui.masking.threshold_mask_dialog import ThresholdMaskDialog
from hexrdgui.transform_dialog import TransformDialog
from hexrdgui.indexing.indexing_tree_view_dialog import IndexingTreeViewDialog
from hexrdgui.indexing.fit_grains_tree_view_dialog import FitGrainsTreeViewDialog
from hexrdgui.image_mode_widget import ImageModeWidget
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals
from hexrdgui.utils.dialog import add_help_url
from hexrdgui.utils.physics_package import (
    ask_to_create_physics_package_if_missing,
)
from hexrdgui.zoom_canvas_dialog import ZoomCanvasDialog
from hexrdgui.rerun_clustering_dialog import RerunClusteringDialog
from hexrdgui.physics_package_manager_dialog import PhysicsPackageManagerDialog
from hexrdgui import resource_loader, state
from hexrd.resources import instrument_templates

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon

    from hexrdgui.image_canvas import ImageCanvas


class MainWindow(QObject):

    # Emitted when a new mask is added
    new_mask_added = Signal(str)

    # Emitted when a new configuration is loaded
    config_loaded = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        image_files: list[str] | None = None,
    ) -> None:
        super().__init__(parent)

        self._powder_runner: PowderRunner | None = None
        self._indexing_config_view: IndexingTreeViewDialog | None = None
        self._fit_grains_config_view: FitGrainsTreeViewDialog | None = None

        loader = UiLoader()
        self.ui = loader.load_file('main_window.ui', parent)
        self.confirm_application_close = True

        HexrdConfig().active_canvas = self.active_canvas

        self.progress_dialog = ProgressDialog(self.ui)
        self.progress_dialog.setWindowTitle('Calibration Running')

        self.messages_widget = MessagesWidget(self.ui)
        dock_widget_contents = self.ui.messages_dock_widget_contents
        dock_widget_contents.layout().addWidget(self.messages_widget.ui)
        self.ui.resizeDocks(
            [self.ui.messages_dock_widget], [80], Qt.Orientation.Vertical
        )

        # Let the left dock widget take up the whole left side
        self.ui.setCorner(Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.ui.setCorner(
            Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea
        )

        self.color_map_editor = ColorMapEditor(
            self.ui.image_tab_widget, self.ui.central_widget
        )
        self.color_map_editor.hide_overlays_during_bc_editing = True
        self.ui.color_map_dock_widgets.layout().addWidget(self.color_map_editor.ui)

        self.image_mode_widget = ImageModeWidget(self.ui.central_widget)
        self.ui.image_mode_dock_widgets.layout().addWidget(self.image_mode_widget.ui)

        self.add_materials_panel()

        self.physics_package_manager_dialog = PhysicsPackageManagerDialog(self.ui)

        self.simple_image_series_dialog = SimpleImageSeriesDialog(self.ui)
        self.llnl_import_tool_dialog = LLNLImportToolDialog(
            self.color_map_editor, self.ui
        )
        self.image_stack_dialog = ImageStackDialog(
            self.ui, self.simple_image_series_dialog
        )

        self.cal_tree_view = CalTreeView(self.ui)
        self.instrument_form_view_widget = InstrumentFormViewWidget(self.ui)
        self.calibration_slider_widget = CalibrationSliderWidget(self.ui)

        tab_texts = ['Tree View', 'Form View', 'Slider View']
        self.ui.calibration_tab_widget.clear()
        self.ui.calibration_tab_widget.addTab(self.cal_tree_view, tab_texts[0])
        self.ui.calibration_tab_widget.addTab(
            self.instrument_form_view_widget.ui, tab_texts[1]
        )
        self.ui.calibration_tab_widget.addTab(
            self.calibration_slider_widget.ui, tab_texts[2]
        )

        url = 'configuration/instrument/'
        add_help_url(self.ui.config_button_box, url)

        self.mask_manager_dialog = MaskManagerDialog(self.ui)

        self._edit_colormap_list_dialog = EditColormapListDialog(
            self.ui, self.color_map_editor
        )

        self.threshold_mask_dialog = ThresholdMaskDialog(self.ui)

        self.setup_connections()

        self.update_config_gui()

        self.update_action_check_states()

        self.update_action_enable_states()

        self.set_live_update(HexrdConfig().live_update)

        self.on_action_show_all_colormaps_toggled(HexrdConfig().show_all_colormaps)

        ImageFileManager().load_dummy_images(True)

        self.update_all_menu_item_tooltips()

        # In order to avoid both a not very nice looking black window,
        # and a bug with the tabbed view
        # (see https://github.com/HEXRD/hexrdgui/issues/261),
        # do not draw the images before the first paint event has
        # occurred. The images will be drawn automatically after
        # the first paint event has occurred (see MainWindow.eventFilter).

        self.add_view_dock_widget_actions()
        self.update_recent_state_files()

    def setup_connections(self) -> None:
        """This is to setup connections for non-gui objects"""
        self.ui.installEventFilter(self)
        self.ui.action_open_instrument_file.triggered.connect(
            self.on_action_open_config_file_triggered
        )
        self.ui.action_open_grain_fitting_results.triggered.connect(
            self.open_grain_fitting_results
        )
        self.ui.action_save_config_yaml.triggered.connect(
            self.on_action_save_config_yaml_triggered
        )
        self.ui.action_save_config_hexrd.triggered.connect(
            self.on_action_save_config_hexrd_triggered
        )
        self.ui.action_open_materials.triggered.connect(
            self.on_action_open_materials_triggered
        )
        self.ui.action_save_imageseries.triggered.connect(
            self.on_action_save_imageseries_triggered
        )
        self.ui.action_save_materials_hdf5.triggered.connect(
            self.on_action_save_materials_hdf5_triggered
        )
        self.ui.action_save_materials_cif.triggered.connect(
            self.on_action_save_materials_cif_triggered
        )
        self.ui.action_save_state.triggered.connect(self.on_action_save_state_triggered)
        self.ui.action_open_state.triggered.connect(self.on_action_load_state_triggered)
        self.ui.action_export_current_plot.triggered.connect(
            self.on_action_export_current_plot_triggered
        )
        self.ui.action_export_to_maud.triggered.connect(
            self.on_action_export_to_maud_triggered
        )
        self.ui.action_edit_euler_angle_convention.triggered.connect(
            self.on_action_edit_euler_angle_convention
        )
        self.ui.action_edit_apply_hand_drawn_mask.triggered.connect(
            self.on_action_edit_apply_hand_drawn_mask_triggered
        )
        self.ui.action_edit_apply_hand_drawn_mask.triggered.connect(
            self.ui.image_tab_widget.toggle_off_toolbar
        )
        self.ui.action_edit_apply_laue_mask_to_polar.triggered.connect(
            self.on_action_edit_apply_laue_mask_to_polar_triggered
        )
        self.ui.action_edit_apply_powder_mask_to_polar.triggered.connect(
            self.action_edit_apply_powder_mask_to_polar
        )
        self.ui.action_edit_apply_region_mask.triggered.connect(
            self.on_action_edit_apply_region_mask_triggered
        )
        self.ui.action_edit_apply_pinhole_mask.triggered.connect(
            self.show_pinhole_mask_dialog
        )
        self.ui.action_edit_reset_instrument_config.triggered.connect(
            self.on_action_edit_reset_instrument_config
        )
        self.ui.action_transform_detectors.triggered.connect(
            self.on_action_transform_detectors_triggered
        )
        self.ui.action_image_calculator.triggered.connect(self.open_image_calculator)
        self.ui.action_edit_config.triggered.connect(
            self.on_action_edit_config_triggered
        )
        self.ui.action_open_mask_manager.triggered.connect(
            self.on_action_open_mask_manager_triggered
        )
        self.ui.action_show_live_updates.toggled.connect(self.set_live_update)
        self.ui.action_show_detector_borders.toggled.connect(
            HexrdConfig().set_show_detector_borders
        )
        self.ui.action_show_beam_marker.toggled.connect(self.show_beam_marker_toggled)
        self.ui.action_view_indexing_config.triggered.connect(self.view_indexing_config)
        self.ui.action_view_fit_grains_config.triggered.connect(
            self.view_fit_grains_config
        )
        self.ui.action_view_overlay_picks.triggered.connect(self.view_overlay_picks)
        self.ui.calibration_tab_widget.currentChanged.connect(self.update_config_gui)
        self.image_mode_widget.tab_changed.connect(self.change_image_mode)
        self.threshold_mask_dialog.mask_applied.connect(self.update_all)
        self.ui.action_run_fast_powder_calibration.triggered.connect(
            self.start_fast_powder_calibration
        )
        self.ui.action_run_laue_and_powder_calibration.triggered.connect(
            self.on_action_run_laue_and_powder_calibration_triggered
        )
        self.ui.action_run_laue_and_powder_calibration.triggered.connect(
            self.ui.image_tab_widget.toggle_off_toolbar
        )
        self.ui.action_run_structureless_calibration.triggered.connect(
            self.run_structureless_calibration
        )
        self.ui.action_run_hedm_calibration.triggered.connect(self.run_hedm_calibration)
        self.ui.action_run_indexing.triggered.connect(
            self.on_action_run_indexing_triggered
        )
        self.ui.action_rerun_clustering.triggered.connect(
            self.on_action_rerun_clustering
        )
        self.ui.action_run_fit_grains.triggered.connect(
            self.on_action_run_fit_grains_triggered
        )
        self.ui.action_run_wppf.triggered.connect(self.run_wppf)
        self.ui.image_tab_widget.update_needed.connect(self.update_all)
        self.ui.image_tab_widget.new_mouse_position.connect(self.new_mouse_position)
        self.ui.image_tab_widget.clear_mouse_position.connect(
            self.ui.status_bar.clearMessage
        )
        self.llnl_import_tool_dialog.new_config_loaded.connect(self.update_config_gui)
        self.llnl_import_tool_dialog.instrument_was_selected.connect(
            self.update_action_check_states
        )
        self.llnl_import_tool_dialog.cancel_workflow.connect(self.load_dummy_images)
        self.config_loaded.connect(self.llnl_import_tool_dialog.config_loaded_from_menu)
        self.ui.action_show_toolbar.toggled.connect(
            self.ui.image_tab_widget.toggle_off_toolbar
        )
        self.ui.action_hedm_import_tool.triggered.connect(
            self.on_action_hedm_import_tool_triggered
        )
        self.ui.action_llnl_import_tool.triggered.connect(
            self.on_action_llnl_import_tool_triggered
        )
        self.ui.action_image_stack.triggered.connect(
            self.on_action_image_stack_triggered
        )
        self.ui.action_show_all_colormaps.triggered.connect(
            self.on_action_show_all_colormaps_toggled
        )
        self.ui.action_edit_defaults.triggered.connect(
            self.on_action_edit_defaults_toggled
        )
        self.ui.image_tab_widget.new_active_canvas.connect(self.active_canvas_changed)
        self.ui.action_edit_apply_threshold.triggered.connect(
            self.on_action_edit_apply_threshold_triggered
        )
        self.ui.action_open_preconfigured_instrument_file.triggered.connect(
            self.on_action_open_preconfigured_instrument_file_triggered
        )
        self.ui.action_edit_physics_package.triggered.connect(
            self.on_action_edit_physics_package_triggered
        )
        self.ui.action_include_physics_package.toggled.connect(
            self.on_action_include_physics_package_toggled
        )

        self.image_mode_widget.polar_show_snip1d.connect(
            self.ui.image_tab_widget.polar_show_snip1d
        )
        self.image_mode_widget.raw_show_zoom_dialog.connect(
            self.on_show_raw_zoom_dialog
        )
        self.image_mode_widget.create_waterfall_plot.connect(
            self.ui.image_tab_widget.create_waterfall_plot
        )

        self.ui.action_open_images.triggered.connect(self.open_image_files_triggered)
        HexrdConfig().update_status_bar.connect(self.ui.status_bar.showMessage)
        HexrdConfig().detectors_changed.connect(self.on_detectors_changed)
        HexrdConfig().detector_shape_changed.connect(self.on_detector_shape_changed)
        HexrdConfig().deep_rerender_needed.connect(self.deep_rerender)
        HexrdConfig().rerender_needed.connect(self.on_rerender_needed)
        MaskManager().raw_masks_changed.connect(self.update_all)
        HexrdConfig().enable_canvas_toolbar.connect(self.on_enable_canvas_toolbar)
        HexrdConfig().tab_images_changed.connect(
            self.update_drawn_mask_line_picker_canvas
        )
        HexrdConfig().tab_images_changed.connect(self.update_mask_region_canvas)
        HexrdConfig().update_instrument_toolbox.connect(self.update_config_gui)
        HexrdConfig().physics_package_modified.connect(self.on_physics_package_modified)

        ImageLoadManager().update_needed.connect(self.update_all)
        ImageLoadManager().new_images_loaded.connect(self.images_loaded)
        ImageLoadManager().images_transformed.connect(self.update_config_gui)
        ImageLoadManager().live_update_status.connect(self.set_live_update)
        ImageLoadManager().state_updated.connect(
            self.simple_image_series_dialog.setup_gui
        )

        self.new_mask_added.connect(self.mask_manager_dialog.update_tree)
        self.image_mode_widget.tab_changed.connect(MaskManager().view_mode_changed)
        self.image_mode_widget.tab_changed.connect(
            self.mask_manager_dialog.update_collapsed
        )

        self.ui.action_apply_pixel_solid_angle_correction.toggled.connect(
            HexrdConfig().set_apply_pixel_solid_angle_correction
        )
        self.ui.action_apply_polarization_correction.toggled.connect(
            self.apply_polarization_correction_toggled
        )
        self.ui.action_apply_lorentz_correction.toggled.connect(
            self.apply_lorentz_correction_toggled
        )
        self.ui.action_subtract_minimum.toggled.connect(
            HexrdConfig().set_intensity_subtract_minimum
        )
        self.ui.action_apply_absorption_correction.toggled.connect(
            self.action_apply_absorption_correction_toggled
        )
        self.ui.action_apply_median_filter.toggled.connect(
            self.action_apply_median_filter_toggled
        )
        HexrdConfig().instrument_config_loaded.connect(self.on_instrument_config_loaded)
        HexrdConfig().active_beam_switched.connect(self.update_config_gui)
        HexrdConfig().state_loaded.connect(self.on_state_loaded)
        HexrdConfig().image_view_loaded.connect(self.on_image_view_loaded)
        HexrdConfig().polar_masks_reapplied.connect(self.on_polar_masks_reapplied)

        self.ui.action_about.triggered.connect(self.on_action_about_triggered)
        self.ui.action_documentation.triggered.connect(
            self.on_action_documentation_triggered
        )

        # Update menu item tooltips when their enable state changes
        for widget_name in self._menu_item_tooltips:
            w = getattr(self.ui, widget_name)
            w.changed.connect(self._update_menu_item_tooltip_for_sender)

        HexrdConfig().enable_canvas_focus_mode.connect(self.enable_canvas_focus_mode)

        self.llnl_import_tool_dialog.complete_workflow.connect(
            self.on_llnl_import_completed
        )

    def on_state_loaded(self) -> None:
        self.update_action_check_states()
        self.update_action_enable_states()
        self.materials_panel.update_gui_from_config()

    def update_action_check_states(self) -> None:
        checkbox_to_hexrd_config_mappings = {
            'action_apply_pixel_solid_angle_correction': (
                'apply_pixel_solid_angle_correction'
            ),
            'action_apply_polarization_correction': 'apply_polarization_correction',
            'action_apply_lorentz_correction': 'apply_lorentz_correction',
            'action_subtract_minimum': 'intensity_subtract_minimum',
            'action_show_live_updates': 'live_update',
            'action_show_detector_borders': 'show_detector_borders',
            'action_show_beam_marker': 'show_beam_marker',
            'action_show_all_colormaps': 'show_all_colormaps',
            'action_apply_absorption_correction': 'apply_absorption_correction',
            'action_include_physics_package': 'has_physics_package',
            'action_apply_median_filter': 'apply_median_filter_correction',
        }

        for cb_name, attr_name in checkbox_to_hexrd_config_mappings.items():
            cb = getattr(self.ui, cb_name)
            with block_signals(cb):
                cb.setChecked(getattr(HexrdConfig(), attr_name))

    def update_action_enable_states(self) -> None:
        enabled_to_hexrd_config_mappings = {
            'action_edit_physics_package': 'has_physics_package',
        }

        for en_name, attr_name in enabled_to_hexrd_config_mappings.items():
            action = getattr(self.ui, en_name)
            with block_signals(action):
                action.setEnabled(getattr(HexrdConfig(), attr_name))

    def set_icon(self, icon: QIcon) -> None:
        self.ui.setWindowIcon(icon)

    def show(self) -> None:
        self.ui.show()

    def add_materials_panel(self) -> None:
        # Remove the placeholder materials panel from the UI, and
        # add the real one.
        materials_panel_index = -1
        for i in range(self.ui.config_tool_box.count()):
            if self.ui.config_tool_box.itemText(i) == 'Materials':
                materials_panel_index = i

        if materials_panel_index < 0:
            raise Exception('"Materials" panel not found!')

        self.ui.config_tool_box.removeItem(materials_panel_index)
        self.materials_panel = MaterialsPanel(self.ui)
        self.ui.config_tool_box.insertItem(
            materials_panel_index, self.materials_panel.ui, 'Materials'
        )

    def enable_canvas_focus_mode(self, b: bool) -> None:
        # Disable these widgets when focus mode is set
        disable_widgets = [
            self.image_mode_widget.ui,
            self.ui.config_tool_box,
            self.ui.menu_bar,
            self.ui.image_tab_widget.tabBar(),
        ]
        # Add image series toolbar widgets
        for tb_dict in self.ui.image_tab_widget.toolbars:
            disable_widgets.append(tb_dict['sb'])

        for w in disable_widgets:
            w.setEnabled(not b)

    def on_instrument_config_loaded(self) -> None:
        self.update_config_gui()

    def on_action_open_config_file_triggered(self) -> None:
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui,
            'Load Configuration',
            HexrdConfig().working_dir,
            'HEXRD files (*.hexrd *.yaml *.yml)',
        )

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)

            HexrdConfig().load_instrument_config(str(path))

    def _save_config(self, extension: str, filter: str) -> None:
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Configuration', HexrdConfig().working_dir, filter
        )

        if selected_file:
            if Path(selected_file).suffix != extension:
                selected_file += extension

            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return HexrdConfig().save_instrument_config(selected_file)

    def on_action_save_config_hexrd_triggered(self) -> None:
        self._save_config('.hexrd', 'HEXRD files (*.hexrd)')

    def on_action_save_config_yaml_triggered(self) -> None:
        self._save_config('.yml', 'YAML files (*.yml)')

    def open_grain_fitting_results(self) -> None:
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui,
            'Open Grain Fitting File',
            HexrdConfig().working_dir,
            'Grain fitting output files (*.out)',
        )

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)

            data = np.loadtxt(selected_file, ndmin=2)
            dialog = FitGrainsResultsDialog(
                data, parent=self.ui, allow_export_workflow=False
            )
            dialog.show()
            self._fit_grains_results_dialog = dialog

    def on_detectors_changed(self) -> None:
        HexrdConfig().reset_overlay_calibration_picks()
        HexrdConfig().clear_overlay_data()
        HexrdConfig().current_imageseries_idx = 0
        self.load_dummy_images()
        self.ui.image_tab_widget.switch_toolbar(0)
        self.simple_image_series_dialog.config_changed()

    def on_detector_shape_changed(self, det_key: str) -> None:
        # We need to load/reset the dummy images if a detector's shape changes.
        # Otherwise, the HexrdConfig().images_dict object will not have images
        # with the correct shape.
        self.load_dummy_images()

    def load_dummy_images(self) -> None:
        if HexrdConfig().loading_state:
            # Don't load the dummy images during state load
            return

        ImageFileManager().load_dummy_images()
        self.update_all(clear_canvases=True)
        self.ui.action_transform_detectors.setEnabled(False)
        # Manually indicate that new images were loaded
        ImageLoadManager().new_images_loaded.emit()

    def open_image_file(self) -> list[str] | None:
        images_dir = HexrdConfig().images_dir

        selected_file, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, dir=images_dir or ""
        )

        if len(selected_file) > 1:
            msg = 'Please select only one file.'
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return None

        return selected_file

    def open_image_files_triggered(self) -> None:
        try:
            self.open_image_files()
        except Exception as e:
            QMessageBox.warning(self.ui, 'HEXRD', str(e))
            return

    def open_image_files(self, selected_files: list[str] | None = None) -> None:
        if selected_files is None:
            # Get the most recent images dir
            images_dir = HexrdConfig().images_dir

            selected_files, selected_filter = QFileDialog.getOpenFileNames(
                self.ui, dir=images_dir or ""
            )

        if selected_files:
            # Save the chosen dir
            HexrdConfig().set_images_dir(selected_files[0])

            files, manual = ImageLoadManager().load_images(selected_files)
            if not files:
                return

            if any(len(f) != 1 for f in files) or len(files) < len(
                HexrdConfig().detector_names
            ):
                msg = 'Number of files must match number of detectors: ' + str(
                    len(HexrdConfig().detector_names)
                )
                raise Exception(msg)

            # If it is a hdf5 file allow the user to select the path
            ext = os.path.splitext(selected_files[0])[1]
            if ImageFileManager().is_hdf(
                ext
            ) and not ImageFileManager().hdf_path_exists(selected_files[0]):

                selection = ImageFileManager().path_prompt(selected_files[0])
                if not selection:
                    return

            dialog = LoadImagesDialog(files, manual, self.ui)

            if dialog.exec():
                results = dialog.results()
                self.files = []
                for det in HexrdConfig().detector_names:
                    self.files.append(results[det])
                image_files = [v for f in results.values() for v in f]
                HexrdConfig().recent_images = image_files
                ImageLoadManager().read_data(files, ui_parent=self.ui)

    def images_loaded(self, enabled: bool = True) -> None:
        self.ui.action_transform_detectors.setEnabled(enabled)
        self.update_color_map_bounds()
        self.update_enable_states()
        self.color_map_editor.reset_range()
        self.update_image_mode_enable_states()

    def on_action_open_materials_triggered(self) -> None:
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui,
            'Load Materials File',
            HexrdConfig().working_dir,
            'All supported files (*.h5 *.hdf5 *.cif);;'
            'HDF5 files (*.h5 *.hdf5);;CIF files (*.cif)',
        )
        if not selected_file:
            return

        HexrdConfig().working_dir = os.path.dirname(selected_file)
        if Path(selected_file).suffix == '.cif':
            HexrdConfig().import_material(selected_file)
        else:
            HexrdConfig().load_materials(selected_file)

    def on_action_save_imageseries_triggered(self) -> None:
        if not HexrdConfig().has_images:
            msg = 'No ImageSeries available for saving.'
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        SaveImagesDialog(self.ui).exec()

    def on_action_save_materials_hdf5_triggered(self) -> None:
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui,
            'Save Materials',
            HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)',
        )

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)

            # Ensure the file name has an hdf5 ending
            acceptable_exts = ['.h5', '.hdf5']
            if not any(selected_file.endswith(x) for x in acceptable_exts):
                selected_file += '.h5'

            return HexrdConfig().save_materials_hdf5(selected_file)

    def on_action_save_materials_cif_triggered(self) -> None:
        caption = 'Select directory to save CIF files to'
        selected_dir = QFileDialog.getExistingDirectory(
            self.ui, caption, dir=HexrdConfig().working_dir
        )
        if not selected_dir:
            return

        HexrdConfig().working_dir = selected_dir
        for material in HexrdConfig().materials.values():
            HexrdConfig().save_material_cif(material, selected_dir)

    def on_action_export_current_plot_triggered(self) -> None:
        filters = 'HDF5 files (*.h5 *.hdf5);; NPZ files (*.npz)'
        if self.image_mode == ViewType.polar:
            # We can do CSV and XY as well
            filters += ';; CSV files (*.csv);; XY files (*.xy)'

        default_name = f'{self.image_mode}_view.h5'
        default_path = os.path.join(HexrdConfig().working_dir, default_name)
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Current View', default_path, filters
        )

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            return self.ui.image_tab_widget.export_current_plot(selected_file)

    def on_action_export_to_maud_triggered(self) -> None:
        filters = 'ESG files (*.esg)'

        default_path = os.path.join(HexrdConfig().working_dir, "maud.esg")
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export to Maud', default_path, filters
        )

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            return self.ui.image_tab_widget.export_to_maud(selected_file)

    def on_action_run_laue_and_powder_calibration_triggered(self) -> None:
        if not hasattr(self, '_calibration_runner_async_runner'):
            # Initialize this only once and keep it around, so we don't
            # run into issues connecting/disconnecting the messages.
            self._calibration_runner_async_runner = AsyncRunner(self.ui)

        async_runner = self._calibration_runner_async_runner
        canvas = self.ui.image_tab_widget.image_canvases[0]
        runner = CalibrationRunner(canvas, async_runner)
        self._calibration_runner = runner
        runner.calibration_finished.connect(self.calibration_finished)

        try:
            runner.run()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            raise

    def calibration_finished(self) -> None:
        self.update_config_gui()
        self.deep_rerender()

    def run_structureless_calibration(self) -> None:
        cached_async_runner_name = '_structureless_calibration_async_runner'
        if not hasattr(self, cached_async_runner_name):
            # Initialize this only once and keep it around, so we don't
            # run into issues connecting/disconnecting the messages.
            setattr(self, cached_async_runner_name, AsyncRunner(self.ui))

        async_runner = getattr(self, cached_async_runner_name)

        canvas = self.ui.image_tab_widget.image_canvases[0]
        runner = StructurelessCalibrationRunner(canvas, async_runner, self.ui)
        runner.instrument_updated.connect(self.structureless_calibration_updated)

        try:
            runner.run()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            raise

    def structureless_calibration_updated(self) -> None:
        self.update_config_gui()
        self.update_all()

    def run_hedm_calibration(self) -> None:
        cached_async_runner_name = '_hedm_calibration_runner_async_runner'
        if not hasattr(self, cached_async_runner_name):
            # Initialize this only once and keep it around, so we don't
            # run into issues connecting/disconnecting the messages.
            setattr(self, cached_async_runner_name, AsyncRunner(self.ui))

        async_runner = getattr(self, cached_async_runner_name)

        runner = HEDMCalibrationRunner(async_runner, self.ui)
        runner.finished.connect(self.on_hedm_calibration_finished)
        try:
            runner.run()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            raise

    def on_hedm_calibration_finished(self) -> None:
        self.update_config_gui()
        self.deep_rerender()

    def on_action_run_indexing_triggered(self) -> None:
        self.ui.action_rerun_clustering.setEnabled(False)
        self._indexing_runner = IndexingRunner(self.ui)
        self._indexing_runner.clustering_ran.connect(
            self.ui.action_rerun_clustering.setEnabled
        )
        self._indexing_runner.run()

    def on_action_rerun_clustering(self) -> None:
        RerunClusteringDialog(self._indexing_runner, self.ui).exec()

    def on_action_run_fit_grains_triggered(self) -> None:
        kwargs = {
            'grains_table': None,
            'indexing_runner': getattr(self, '_indexing_runner', None),
            'started_from_indexing': False,
            'parent': self.ui,
        }
        runner = self._grain_fitting_runner = FitGrainsRunner(**kwargs)
        runner.run()

    def run_wppf(self) -> None:
        self._wppf_runner = WppfRunner(self.ui)
        try:
            self._wppf_runner.run()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            raise

    def update_color_map_bounds(self) -> None:
        self.color_map_editor.update_bounds(HexrdConfig().masked_images_dict)

    def on_action_edit_euler_angle_convention(self) -> None:
        allowed_conventions = ['None', 'Extrinsic XYZ', 'Intrinsic ZXZ']
        corresponding_values = [
            None,
            {'axes_order': 'xyz', 'extrinsic': True},
            {'axes_order': 'zxz', 'extrinsic': False},
        ]
        current = HexrdConfig().euler_angle_convention
        ind = corresponding_values.index(current)

        help_url = 'configuration/instrument/#euler-angle-convention'
        name, ok = InputDialog.getItem(
            self.ui,
            'HEXRD',
            'Select Euler Angle Convention',
            allowed_conventions,
            ind,
            False,
            help_url=help_url,
        )

        if not ok or name is None:
            # User canceled...
            return

        chosen = corresponding_values[allowed_conventions.index(name)]
        HexrdConfig().set_euler_angle_convention(chosen)

        self.update_all()
        self.update_config_gui()

    @property
    def active_canvas(self) -> ImageCanvas | None:
        return self.ui.image_tab_widget.active_canvas

    def active_canvas_changed(self) -> None:
        # Update the active canvas on HexrdConfig()
        HexrdConfig().active_canvas = self.active_canvas
        self.update_drawn_mask_line_picker_canvas()
        self.update_mask_region_canvas()

    def update_drawn_mask_line_picker_canvas(self) -> None:
        if hasattr(self, '_apply_drawn_mask_line_picker'):
            self._apply_drawn_mask_line_picker.canvas_changed(self.active_canvas)

    def on_action_edit_apply_hand_drawn_mask_triggered(self) -> None:
        # Make the dialog
        self._apply_drawn_mask_line_picker = HandDrawnMaskDialog(
            self.active_canvas, self.ui
        )
        self._apply_drawn_mask_line_picker.start()
        self._apply_drawn_mask_line_picker.finished.connect(
            self.run_apply_hand_drawn_mask
        )

    def run_apply_hand_drawn_mask(
        self, dets: list[str | None], line_data: list[np.ndarray]
    ) -> None:
        if self.image_mode == ViewType.polar:
            for line in line_data:
                raw_line = convert_polar_to_raw([line])
                MaskManager().add_mask(raw_line, MaskType.polygon)
            MaskManager().polar_masks_changed.emit()
        elif self.image_mode == ViewType.raw:
            for det, line in zip(dets, line_data):
                MaskManager().add_mask([(det, line.copy())], MaskType.polygon)
            MaskManager().raw_masks_changed.emit()
        self.new_mask_added.emit(self.image_mode)

    def on_action_edit_apply_laue_mask_to_polar_triggered(self) -> None:
        if not HexrdConfig().show_overlays:
            msg = 'Overlays are not displayed'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        overlays = HexrdConfig().overlays
        laue_overlays = [x for x in overlays if x.is_laue and x.visible]
        if not laue_overlays:
            msg = 'No Laue overlays found'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        data = []
        for overlay in laue_overlays:
            for det, val in overlay.data.items():
                for ranges in val['ranges']:
                    data.append(ranges)

        if not data:
            msg = 'No Laue overlay ranges found'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        raw_data = convert_polar_to_raw(data)
        MaskManager().add_mask(raw_data, MaskType.laue)
        self.new_mask_added.emit(self.image_mode)
        MaskManager().polar_masks_changed.emit()

    def action_edit_apply_powder_mask_to_polar(self) -> None:
        if not HexrdConfig().show_overlays:
            msg = 'Overlays are not displayed'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        overlays = HexrdConfig().overlays
        powder_overlays = [x for x in overlays if x.is_powder and x.visible]
        if not powder_overlays:
            msg = 'No powder overlays found'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        data = []
        for overlay in powder_overlays:
            for _, val in overlay.data.items():
                # We will only apply masks for ranges that have both a
                # start and a stop.
                start_end_pairs: dict[str, Any] = {}
                for i, indices in enumerate(val['rbnd_indices']):
                    for idx in indices:
                        # Get the pair for this HKL index
                        pairs = start_end_pairs.setdefault(idx, [])
                        if len(pairs) == 2:
                            # We already got this one (this shouldn't happen)
                            continue

                        pairs.append(val['rbnds'][i])

                        # We only want to use the ranges once each.
                        # Since we found a use of this range already,
                        # just break.
                        break

                for key in list(start_end_pairs):
                    # Remove any ranges that have a missing half
                    if len(start_end_pairs[key]) < 2:
                        del start_end_pairs[key]

                for start, end in start_end_pairs.values():
                    ranges = np.append(start, np.flip(end, axis=0), axis=0)
                    ranges = np.append(ranges, [ranges[0]], axis=0)
                    data.append(ranges[~np.isnan(ranges).any(axis=1)])

        if not data:
            msg = 'No powder overlay ranges found'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        raw_data = convert_polar_to_raw(data)
        MaskManager().add_mask(raw_data, MaskType.powder)
        self.new_mask_added.emit(self.image_mode)
        MaskManager().polar_masks_changed.emit()

    def update_mask_region_canvas(self) -> None:
        if hasattr(self, '_masks_regions_dialog'):
            self._masks_regions_dialog.canvas_changed(self.active_canvas)

    def on_action_edit_apply_region_mask_triggered(self) -> None:
        self._masks_regions_dialog = MaskRegionsDialog(self.ui)
        self._masks_regions_dialog.new_mask_added.connect(self.new_mask_added.emit)
        self._masks_regions_dialog.show()

        self.ui.image_tab_widget.toggle_off_toolbar()

    def show_pinhole_mask_dialog(self) -> None:
        if not ask_to_create_physics_package_if_missing():
            # Physics package is required, but user did not create one.
            return

        if not hasattr(self, '_pinhole_mask_dialog'):
            self._pinhole_mask_dialog = PinholeMaskDialog(self.ui)
            self._pinhole_mask_dialog.apply_clicked.connect(self.apply_pinhole_mask)

        self._pinhole_mask_dialog.show()

    def apply_pinhole_mask(self) -> None:
        instr = create_hedm_instrument()
        ph_buffer = generate_pinhole_panel_buffer(instr)

        ph_masks = []
        for det_key, buffer in ph_buffer.items():
            # Expand it so we get a contour around the whole masked regions
            expanded_shape = tuple(x + 4 for x in buffer.shape)
            expanded_array = np.zeros(expanded_shape, dtype=bool)
            expanded_array[2:-2, 2:-2] = ~buffer

            contours = measure.find_contours(expanded_array)

            for contour in contours:
                # Fix the coordinates
                contour -= 2

                # Swap x and y
                contour[:, [1, 0]] = contour[:, [0, 1]]

                ph_masks.append((det_key, contour))

        if not ph_masks:
            msg = (
                'Failed to find contours to generate the pinhole mask. '
                'Please ensure the input is reasonable.'
            )
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        # Overwrite previous pinhole masks
        name = 'pinhole_mask'
        if name in MaskManager().mask_names:
            MaskManager().masks[name].data = ph_masks
        else:
            MaskManager().add_mask(ph_masks, MaskType.pinhole, name=name)
        MaskManager().raw_masks_changed.emit()

        self.new_mask_added.emit(self.image_mode)

    def on_action_edit_reset_instrument_config(self) -> None:
        HexrdConfig().restore_instrument_config_backup()
        self.update_config_gui()

    def on_show_raw_zoom_dialog(self) -> None:
        assert self.active_canvas is not None
        dialog = ZoomCanvasDialog(self.active_canvas, parent=self.ui)
        self._zoom_dialog = dialog
        dialog.show()

        # By default, update the zoom width and height to be 1/5 of shape
        img = dialog.zoom_canvas.rsimg
        dialog.zoom_width = int(img.shape[1] / 5)
        dialog.zoom_height = int(img.shape[0] / 5)

    def change_image_mode(self, mode: str) -> None:
        # The masking canvas change needs to be triggered *before* the image
        # mode is changed. This makes sure that in-progress masks are completed
        # and associated with the correct image mode.
        self.update_drawn_mask_line_picker_canvas()
        self.update_mask_region_canvas()
        self.image_mode = mode
        self.update_image_mode_enable_states()

        # Clear the overlays
        HexrdConfig().clear_overlay_data()

        self.update_all()

    def update_image_mode_enable_states(self) -> None:
        # This is for enable states that depend on the image mode
        is_cartesian = self.image_mode == ViewType.cartesian
        is_polar = self.image_mode == ViewType.polar
        is_raw = self.image_mode == ViewType.raw
        is_stereo = self.image_mode == ViewType.stereo

        has_images = HexrdConfig().has_images

        self.ui.action_export_current_plot.setEnabled(
            (is_polar or is_cartesian or is_stereo) and has_images
        )
        self.ui.action_run_laue_and_powder_calibration.setEnabled(
            is_polar and has_images
        )
        self.ui.action_run_structureless_calibration.setEnabled(is_polar and has_images)
        self.ui.action_edit_apply_hand_drawn_mask.setEnabled(
            (is_polar or is_raw) and has_images
        )
        self.ui.action_run_wppf.setEnabled(is_polar and has_images)
        self.ui.action_edit_apply_laue_mask_to_polar.setEnabled(is_polar)
        self.ui.action_edit_apply_powder_mask_to_polar.setEnabled(is_polar)
        self.ui.action_export_to_maud.setEnabled(is_polar and has_images)

    def start_fast_powder_calibration(self) -> None:
        if not HexrdConfig().has_images:
            msg = 'No images available for calibration.'
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        if self._powder_runner is not None:
            self._powder_runner.clear()

        self._powder_runner = runner = PowderRunner(self.ui)
        runner.calibration_finished.connect(self.calibration_finished)
        runner.run()

    def update_config_gui(self) -> None:
        current_widget = self.ui.calibration_tab_widget.currentWidget()
        if current_widget is self.cal_tree_view:
            self.cal_tree_view.rebuild_tree()
        elif current_widget is self.instrument_form_view_widget.ui:
            self.instrument_form_view_widget.update_gui_from_config()
        elif current_widget is self.calibration_slider_widget.ui:
            self.calibration_slider_widget.update_gui_from_config()
        self.config_loaded.emit()

    def eventFilter(self, target: QObject, event: QEvent) -> bool:
        if type(target) is QMainWindow:
            if event.type() == QEvent.Type.Close:
                if self.confirm_application_close:
                    msg = 'Are you sure you want to quit?'
                    response = QMessageBox.question(self.ui, 'HEXRD', msg)
                    if response == QMessageBox.StandardButton.No:
                        event.ignore()
                        return True
                # If the main window is closing, save the config settings
                HexrdConfig().save_settings()
            elif event.type() in (QEvent.Type.DragEnter, QEvent.Type.Drop):
                self.validateDragDropEvent(event)
                return True

        if not hasattr(self, '_first_paint_occurred'):
            if type(target) is QMainWindow and event.type() == QEvent.Type.Paint:
                # Draw the images for the first time after the first paint
                # has occurred in order to avoid a black window.
                QTimer.singleShot(0, self.update_all)
                self._first_paint_occurred = True

        return False

    def update_if_mode_matches(
        self,
        mode: str,
    ) -> None:
        if self.image_mode == mode:
            self.update_all()

    def deep_rerender(self) -> None:
        # Clear all overlays
        HexrdConfig().clear_overlay_data()

        # Update all and clear the canvases
        self.update_all(clear_canvases=True)

    def update_all(self, clear_canvases: bool = False) -> None:
        # If there are no images loaded, skip the request
        if not HexrdConfig().imageseries_dict:
            return

        if HexrdConfig().loading_state:
            # Skip the request if we are loading state
            return

        prev_blocked = self.instrument_form_view_widget.block_all_signals()

        # Need to clear focus from current widget if enter is pressed or
        # else all clicks are emit an editingFinished signal and view is
        # constantly re-rendered
        focus_widget = QApplication.focusWidget()
        if focus_widget is not None:
            focus_widget.clearFocus()

        if clear_canvases:
            for canvas in self.ui.image_tab_widget.image_canvases:
                canvas.clear()

        if self.image_mode == ViewType.cartesian:
            self.ui.image_tab_widget.show_cartesian()
        elif self.image_mode == ViewType.polar:
            rebuild_polar_masks()
            self.ui.image_tab_widget.show_polar()
        elif self.image_mode == ViewType.stereo:
            # Need to rebuild the polar masks since stereo may be using them
            rebuild_polar_masks()
            self.ui.image_tab_widget.show_stereo()
        else:
            rebuild_raw_masks()
            self.ui.image_tab_widget.load_images()

        self.instrument_form_view_widget.unblock_all_signals(prev_blocked)

    def set_live_update(self, enabled: bool) -> None:
        HexrdConfig().live_update = enabled

        if enabled:
            # Go ahead and trigger an update as well
            self.update_all()

    def on_rerender_needed(self) -> None:
        # Only perform an update if we have live updates enabled
        if HexrdConfig().live_update:
            self.update_all()

    def on_enable_canvas_toolbar(self, b: bool) -> None:
        prev_state_name = '_previous_action_show_toolbar_state'
        w = self.ui.action_show_toolbar

        if b == w.isEnabled():
            # It already matches, just ignore
            return

        w.setEnabled(b)
        if not b:
            setattr(self, prev_state_name, w.isChecked())
            w.setChecked(False)
        else:
            checked = getattr(self, prev_state_name, True)
            w.setChecked(checked)

    def show_beam_marker_toggled(self, b: bool) -> None:
        HexrdConfig().show_beam_marker = b
        if b:
            # Also show the style editor dialog
            if not hasattr(self, '_beam_marker_style_editor'):
                self._beam_marker_style_editor = BeamMarkerStyleEditor(self.ui)

            self._beam_marker_style_editor.show()

    def view_indexing_config(self) -> None:
        if self._indexing_config_view is not None:
            self._indexing_config_view.reject()

        view = self._indexing_config_view = IndexingTreeViewDialog(self.ui)
        view.show()

    def view_fit_grains_config(self) -> None:
        if self._fit_grains_config_view is not None:
            self._fit_grains_config_view.reject()

        view = self._fit_grains_config_view = FitGrainsTreeViewDialog(self.ui)
        view.show()

    def view_overlay_picks(self) -> None:
        # Only works in the polar view right now, but could in theory work in
        # other views.
        if self.image_mode != ViewType.polar:
            msg = (
                'Overlay picks may currently only be viewed in the polar ' 'image mode'
            )
            print(msg)
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        canvas = self.ui.image_tab_widget.image_canvases[0]

        overlays = HexrdConfig().overlays

        kwargs = {
            'dictionary': overlays_to_tree_format(overlays),
            'coords_type': ViewType.polar,
            'canvas': canvas,
            'parent': canvas,
        }
        dialog = HKLPicksTreeViewDialog(**kwargs)
        dialog.button_box_visible = True
        dialog.ui.show()

        def remove_all_highlighting() -> None:
            for overlay in overlays:
                overlay.clear_highlights()
            HexrdConfig().flag_overlay_updates_for_all_materials()
            HexrdConfig().overlay_config_changed.emit()

        def on_accepted() -> None:
            # Write the modified picks to the overlays
            updated_picks = tree_format_to_picks(overlays, dialog.dictionary)
            for i, new_picks in enumerate(updated_picks):
                overlays[i].calibration_picks_polar = new_picks['picks']

        def on_finished() -> None:
            remove_all_highlighting()

        dialog.ui.accepted.connect(on_accepted)
        dialog.ui.finished.connect(on_finished)

    def new_mouse_position(self, info: dict[str, Any]) -> None:
        if self.image_mode == ViewType.polar:
            # Use a special function for polar
            labels = self.polar_mouse_info_labels(info)
        else:
            labels = self.default_mouse_info_labels(info)

        delimiter = ',  '
        msg = delimiter.join(labels)
        self.ui.status_bar.showMessage(msg)

    def default_mouse_info_labels(self, info: dict[str, Any]) -> list[str]:
        labels = []
        labels.append(f'x = {info["x_data"]:8.3f}')
        labels.append(f'y = {info["y_data"]:8.3f}')

        intensity = info['intensity']
        if intensity is not None:
            material_name = info.get("material_name", "")

            labels.append(f'value = {info["intensity"]:8.3f}')
            labels.append(f'tth = {info["tth"]:8.3f}')
            labels.append(f'eta = {info["eta"]:8.3f}')
            labels.append(f'dsp = {info["dsp"]:8.3f}')
            labels.append(f'chi = {info["chi"]:8.3f}')
            labels.append(f'Q = {info["Q"]:8.3f}')
            labels.append(f'hkl ({material_name}) = {info["hkl"]}')

        if 'detectors_str' in info:
            labels.append(info['detectors_str'])

        if 'masks_str' in info:
            labels.append(info['masks_str'])

        return labels

    def polar_mouse_info_labels(self, info: dict[str, Any]) -> list[str]:
        labels = []
        # Assume x is tth in the polar view
        labels.append(f'tth = {info["x_data"]:8.3f}')

        if info.get('is_lineout'):
            # We are in the azimuthal integration plot
            labels.append(f'intensity = {info["y_data"]:8.3f}')
            # Q should have still be calculated.
            labels.append(f'Q = {info["Q"]:8.3f}')
        else:
            # We are in the main polar canvas
            material_name = info.get("material_name", "")

            labels.append(f'eta = {info["y_data"]:8.3f}')
            labels.append(f'value = {info["intensity"]:8.3f}')
            labels.append(f'dsp = {info["dsp"]:8.3f}')
            labels.append(f'chi = {info["chi"]:8.3f}')
            labels.append(f'Q = {info["Q"]:8.3f}')
            labels.append(f'hkl ({material_name}) = {info["hkl"]}')

        if 'detectors_str' in info:
            labels.append(info['detectors_str'])

        if 'masks_str' in info:
            labels.append(info['masks_str'])

        return labels

    def on_action_transform_detectors_triggered(self) -> None:
        _ = TransformDialog(self.ui).exec()

    def open_image_calculator(self) -> None:
        if dialog := getattr(self, '_image_calculator_dialog', None):
            dialog.hide()

        dialog = ImageCalculatorDialog(HexrdConfig().images_dict, self.ui)
        dialog.show()
        self._image_calculator_dialog = dialog

        def on_accepted() -> None:
            ims = dialog.calculate()

            # Replace the current image series with this one
            HexrdConfig().imageseries_dict[dialog.detector] = ims

            # Rerender
            self.update_all()

        dialog.accepted.connect(on_accepted)

    def on_action_edit_config_triggered(self) -> None:
        ConfigDialog(self.ui).exec()

    def update_enable_states(self) -> None:
        has_images = HexrdConfig().has_images
        num_images = HexrdConfig().imageseries_length

        enable_image_calculator = has_images and num_images == 1
        self.ui.action_image_calculator.setEnabled(enable_image_calculator)

        # Update the HEDM enable states
        self.update_hedm_enable_states()

    def update_hedm_enable_states(self) -> None:
        actions = (self.ui.action_run_indexing, self.ui.action_run_fit_grains)
        for action in actions:
            action.setEnabled(False)

        image_series_dict = HexrdConfig().unagg_images
        if not image_series_dict:
            return

        # Check length of first series
        series = next(iter(image_series_dict.values()))
        if not len(series) > 1:
            return

        # If we made it here, they should be enabled.
        for action in actions:
            action.setEnabled(True)

    @property
    def image_mode(self) -> str:
        return HexrdConfig().image_mode

    @image_mode.setter
    def image_mode(self, b: str) -> None:
        HexrdConfig().image_mode = b

    @property
    def _menu_item_tooltips(self) -> dict[str, dict[bool, str]]:
        # The keys here are QAction names. The value is a dict where the keys
        # are the enable state, and the values are the tooltips for that
        # enable state.
        return {
            'action_edit_apply_hand_drawn_mask': {
                True: '',
                False: 'Polar/raw view must be active with image data loaded',
            },
            'action_edit_apply_laue_mask_to_polar': {
                True: '',
                False: 'Polar view must be active',
            },
            'action_edit_apply_powder_mask_to_polar': {
                True: '',
                False: 'Polar view must be active',
            },
            'action_export_current_plot': {
                True: '',
                False: (
                    'Cartesian/polar/stereo view must be active '
                    'with image data loaded'
                ),
            },
            'action_export_to_maud': {
                True: '',
                False: 'Polar view must be active with image data loaded',
            },
            'action_image_calculator': {
                True: '',
                False: (
                    'Image data must be loaded (and must not be an image ' 'stack)'
                ),
            },
            'action_run_laue_and_powder_calibration': {
                True: '',
                False: 'Polar view must be active with image data loaded',
            },
            'action_run_structureless_calibration': {
                True: '',
                False: 'Polar view must be active with image data loaded',
            },
            'action_rerun_clustering': {
                True: '',
                False: 'Indexing must have been ran to re-run clustering',
            },
            'action_run_fit_grains': {
                True: '',
                False: 'An image stack with omega values is required',
            },
            'action_run_indexing': {
                True: '',
                False: 'An image stack with omega values is required',
            },
            'action_run_wppf': {
                True: '',
                False: 'The polar view must be active with image data loaded',
            },
            'action_transform_detectors': {
                True: '',
                False: 'Image data must be loaded',
            },
        }

    def _update_menu_item_tooltip_for_sender(self) -> None:
        # This function should be called automatically when the sending
        # QAction is modified.
        # The modification may have been its enable state.

        w = self.sender()
        enabled = w.isEnabled()  # type: ignore[attr-defined]
        name = w.objectName()

        tooltips = self._menu_item_tooltips
        if name not in tooltips:
            return

        w.setToolTip(tooltips[name][enabled])  # type: ignore[attr-defined]

    def update_all_menu_item_tooltips(self) -> None:
        tooltips = self._menu_item_tooltips

        for widget_name, tooltip_options in tooltips.items():
            w = getattr(self.ui, widget_name)
            enabled = w.isEnabled()
            w.setToolTip(tooltip_options[enabled])

    def on_action_open_mask_manager_triggered(self) -> None:
        self.mask_manager_dialog.show()

    def on_action_save_state_triggered(self) -> None:

        selected_file, _ = QFileDialog.getSaveFileName(
            self.ui,
            'Save Current State',
            HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)',
        )

        if not selected_file:
            return

        overwriting_last_loaded = False
        if selected_file == HexrdConfig().last_loaded_state_file:
            # We are over-writing the last loaded state file.
            # We must save to a temp file to avoid over-writing the
            # imageseries, which are already open...
            # We'll then load the imageseries back in
            overwriting_last_loaded = True

            # Make a temporary file to use for saving
            temp = tempfile.NamedTemporaryFile(delete=False)
            temp.close()
            save_file = temp.name
        else:
            save_file = selected_file

        with h5py.File(save_file, 'w') as h5_file:
            state.save(h5_file)

        if overwriting_last_loaded:
            # Clear the imageseries dict so that the files get closed
            HexrdConfig().imageseries_dict.clear()

            # Move the save file to the selected file
            shutil.move(save_file, selected_file)

            # Re-load the imageseries
            # Keep the file open and let the imageseries close it...
            HexrdConfig().loading_state = True
            self.color_map_editor.block_updates(True)
            try:
                h5_file = h5py.File(selected_file, 'r')
                state.load_imageseries_dict(h5_file)
            finally:
                HexrdConfig().loading_state = False
                self.color_map_editor.block_updates(False)

        HexrdConfig().working_dir = os.path.dirname(selected_file)

        # Show the loaded state in the window title
        self.ui.setWindowTitle(f'HEXRD - {Path(selected_file).name}')

    def load_entrypoint_file(self, filepath: str | Path) -> None:
        # First, identify what type of entrypoint file it is, and then
        # load based upon whatever it is.

        filepath = Path(filepath)
        if filepath.suffix in ('.yml', '.hexrd'):
            # It is an instrument file
            HexrdConfig().load_instrument_config(str(filepath))
            return

        # Assume it is a state file
        self.load_state_file(filepath)

    def on_action_load_state_triggered(self) -> None:
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load State', HexrdConfig().working_dir, 'HDF5 files (*.h5 *.hdf5)'
        )

        if not selected_file:
            return

        self.load_state_file(selected_file)

    def load_state_file(self, filepath: str | Path) -> None:
        path = Path(filepath)
        if not path.exists():
            raise OSError(2, 'No such file or directory', filepath)

        HexrdConfig().working_dir = str(path.parent)

        # Some older state files have issues that need to be resolved.
        # Perform an update, if needed, to fix them, before reading.
        state.update_if_needed(str(filepath))

        # The image series will take care of closing the file
        h5_file = h5py.File(filepath, "r")
        try:
            state.load(h5_file)
        except Exception:
            # If an exception occurred, assume we should close the file...
            h5_file.close()
            raise

        # Remember the state file in the recent files list
        HexrdConfig().add_recent_state_file(filepath)
        self.update_recent_state_files()

        # Show the loaded state in the window title
        self.ui.setWindowTitle(f'HEXRD - {path.name}')

        # Since statuses are added after the instrument config is loaded,
        # the statuses in the GUI might not be up to date. Ensure it is.
        self.update_config_gui()

    def add_view_dock_widget_actions(self) -> None:
        # Add actions to show/hide all of the dock widgets
        dock_widgets = self.ui.findChildren(QDockWidget)
        titles = [w.windowTitle() for w in dock_widgets]
        for title, w in sorted(zip(titles, dock_widgets)):
            self.ui.view_dock_widgets.addAction(w.toggleViewAction())

    def apply_polarization_correction_toggled(self, b: bool) -> None:
        if not b:
            # Just turn it off and return
            HexrdConfig().apply_polarization_correction = b
            return

        # Get the user to first select the Lorentz polarization options
        d = PolarizationOptionsDialog(self.ui)
        if not d.exec():
            # Canceled... uncheck the action.
            action = self.ui.action_apply_polarization_correction
            action.setChecked(False)
            return

        # The dialog should have modified HexrdConfig's polarization
        # options already. Just apply it now.
        HexrdConfig().apply_polarization_correction = b

    def apply_lorentz_correction_toggled(self, b: bool) -> None:
        HexrdConfig().apply_lorentz_correction = b

    def on_action_hedm_import_tool_triggered(self) -> None:
        self.simple_image_series_dialog.show()

    def on_llnl_import_completed(self, is_fiddle_instrument: bool) -> None:
        if is_fiddle_instrument:
            if self.ui.action_apply_median_filter.isChecked():
                # Un-check the median filter if already checked - this ensures we
                # always trigger the callback for the FIDDLE instrument and the
                # kernel setting dialog is always shown
                self.ui.action_apply_median_filter.setChecked(False)
            self.ui.action_apply_median_filter.setChecked(True)
        # Always assume Physics Package is needed for LLNL import
        self.on_action_include_physics_package_toggled(True)

    def on_action_llnl_import_tool_triggered(self) -> None:
        dialog = self.llnl_import_tool_dialog
        dialog.show()

    def on_action_image_stack_triggered(self) -> None:
        self.image_stack_dialog.show()

    def on_image_view_loaded(
        self,
        images: dict[str, np.ndarray],
    ) -> None:
        # Update the data, but don't reset the bounds
        # This will update the histogram in the B&C editor
        self.color_map_editor.data = images

    def on_polar_masks_reapplied(
        self,
        image: np.ndarray,
    ) -> None:
        # Update the data, but don't reset the bounds
        # This will update the histogram in the B&C editor
        self.color_map_editor.data = image

    def on_action_about_triggered(self) -> None:
        dialog = AboutDialog(self.ui)
        dialog.ui.exec()

    def on_action_documentation_triggered(self) -> None:
        QDesktopServices.openUrl(QUrl(DOCUMENTATION_URL))

    def on_action_show_all_colormaps_toggled(self, checked: bool) -> None:
        HexrdConfig().show_all_colormaps = checked
        self.color_map_editor.load_cmaps()

    def on_action_edit_defaults_toggled(self) -> None:
        self._edit_colormap_list_dialog.show()

    def on_action_edit_apply_threshold_triggered(self) -> None:
        self.threshold_mask_dialog.show()

    @property
    def thread_pool(self) -> QThreadPool:
        return QThreadPool.globalInstance()

    def update_recent_state_files(self) -> None:
        # Update actions to list recent state files for quick load
        recents_menu = self.ui.menu_open_recent
        [recents_menu.removeAction(a) for a in recents_menu.actions()]

        recent_state_files = HexrdConfig().recent_state_files
        if not recent_state_files:
            # Put in a placeholder action. Otherwise, the menu will not
            # render correctly when we add the real actions later.
            recents_menu.addAction('None')
            return

        for idx in range(len(recent_state_files)):
            recent = recent_state_files[idx]
            action = recents_menu.addAction(Path(recent).name)
            action.triggered.connect(partial(self.load_recent_state_file, recent))

    def load_recent_state_file(self, path: str) -> None:
        if not Path(path).exists():
            msg = (
                f'Recent state file: "{path}"\n\nno longer exists. '
                'Remove from recent files list?'
            )
            response = QMessageBox.question(self.ui, 'HEXRD', msg)
            if response == QMessageBox.StandardButton.Yes:
                HexrdConfig().recent_state_files.remove(path)
                self.update_recent_state_files()

            return

        self.load_state_file(path)

    def on_action_open_preconfigured_instrument_file_triggered(self) -> None:
        # Should we put this in HEXRD?
        aliases = {
            'dcs.yml': 'DCS',
            'dual_dexelas.yml': 'Dual Dexelas',
            'rigaku.hexrd': 'Rigaku',
            'varex.yml': 'Varex',
        }

        # Create a dict of options for loading an instrument, mapping file
        # name to instrument config
        options = {}
        for f in resource_loader.module_contents(instrument_templates):
            if f.endswith(('.yml', '.yaml', '.hexrd', '.h5', '.hdf5')):
                name = Path(f).name
                if name in aliases:
                    name = aliases[name]

                options[name] = f

        # Sort them in alphabetical order
        options = {k: options[k] for k in sorted(options)}

        # Provide simple dialog for selecting instrument to import
        msg = 'Select pre-configured instrument to load'
        instr_name, ok = QInputDialog.getItem(
            self.ui, 'Load Instrument', msg, list(options), 0, False
        )

        if not ok:
            return

        fname = options[instr_name]
        with resource_loader.resource_path(instrument_templates, fname) as f:
            HexrdConfig().load_instrument_config(Path(f))

    def on_action_edit_physics_package_triggered(self) -> None:
        self.physics_package_manager_dialog.show()

    def on_action_include_physics_package_toggled(self, b: bool) -> None:
        self.ui.action_edit_physics_package.setEnabled(b)
        if b and not HexrdConfig().has_physics_package:
            HexrdConfig().create_default_physics_package()

        if not b:
            # Just turn it off and return
            HexrdConfig().physics_package = None
            return

        # Get the user to select the physics package options
        dialog = self.physics_package_manager_dialog
        dialog.show(delete_if_canceled=True)

    def on_physics_package_modified(self) -> None:
        enable = HexrdConfig().has_physics_package
        w = self.ui.action_include_physics_package
        with block_signals(w):
            w.setChecked(enable)

        self.ui.action_edit_physics_package.setEnabled(enable)

    def action_apply_absorption_correction_toggled(self, b: bool) -> None:
        if not b:
            # Just turn it off and return
            HexrdConfig().apply_absorption_correction = b
            return

        # Get the user to first select the absorption correction options
        d = AbsorptionCorrectionOptionsDialog(self.ui)
        if not d.exec():
            # Canceled... uncheck the action.
            action = self.ui.action_apply_absorption_correction
            action.setChecked(False)
            return

        # The dialog should have modified HexrdConfig's absorption
        # correction options already. Just apply it now.
        HexrdConfig().apply_absorption_correction = b

    def action_apply_median_filter_toggled(self, b: bool) -> None:
        if not b:
            # Just turn it off and return
            HexrdConfig().apply_median_filter_correction = b
            return

        dialog = MedianFilterDialog(self.ui)
        if not dialog.exec():
            # User canceled. Uncheck the action.
            action = self.ui.action_apply_median_filter
            action.setChecked(False)
            return

        # The dialog should have modified HexrdConfig's median filter options
        # already. Just apply it now.
        HexrdConfig().apply_median_filter_correction = b

    def validateDragDropEvent(self, event: QEvent) -> None:
        mime_data = event.mimeData()  # type: ignore[attr-defined]
        if not mime_data.hasUrls():
            event.ignore()
            return

        paths = [url.toLocalFile() for url in mime_data.urls()]
        if event.type() == QEvent.Type.Drop:
            self.dropEvent(paths)
        else:
            event.acceptProposedAction()  # type: ignore[attr-defined]

    def dropEvent(self, paths: Sequence[str | Path]) -> None:
        ext = Path(paths[0]).suffix.lower()
        if len(paths) == 1 and ext in ('.h5', '.hdf5'):
            try:
                # Try loading it as a state file
                self.load_state_file(paths[0])
                return
            except Exception:
                # If that fails, continue on to try a different loader
                pass
        if len(paths) == 1 and ext in ('.hexrd', '.yml', '.yaml'):
            try:
                # Try loading it as an instrument config
                HexrdConfig().load_instrument_config(paths[0])
                return
            except Exception:
                # If that fails, continue on to try a different loader
                pass
        if ext in ('.h5', '.hdf5', '.cif'):
            try:
                # Try loading as materials file(s)
                HexrdConfig().import_materials(list(paths))
                return
            except Exception:
                # If that fails, continue on to try a different loader
                pass
        try:
            # Fall back to trying to load as image if no loader succeeds or
            # extension is not in known list
            self.open_image_files(selected_files=[str(p) for p in paths])
        except Exception:
            error_message = (
                'Unable to guess file type (state, instrument, materials, or '
                'image). Please use File menu to load.'
            )
            QMessageBox.critical(self.ui, 'Error', error_message)
