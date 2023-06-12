import os
from pathlib import Path
import shutil
import tempfile

import h5py
from hexrd.ui.edit_colormap_list_dialog import EditColormapListDialog
import numpy as np
from skimage import measure

from PySide2.QtCore import (
    QEvent, QObject, Qt, QThreadPool, Signal, QTimer, QUrl
)
from PySide2.QtGui import QDesktopServices
from PySide2.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QMainWindow, QMessageBox
)

from hexrd.ui.about_dialog import AboutDialog
from hexrd.ui.async_runner import AsyncRunner
from hexrd.ui.beam_marker_style_editor import BeamMarkerStyleEditor
from hexrd.ui.calibration_slider_widget import CalibrationSliderWidget
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.progress_dialog import ProgressDialog
from hexrd.ui.cal_tree_view import CalTreeView
from hexrd.ui.hand_drawn_mask_dialog import HandDrawnMaskDialog
from hexrd.ui.image_stack_dialog import ImageStackDialog
from hexrd.ui.indexing.run import FitGrainsRunner, IndexingRunner
from hexrd.ui.indexing.fit_grains_results_dialog import FitGrainsResultsDialog
from hexrd.ui.input_dialog import InputDialog
from hexrd.ui.instrument_form_view_widget import InstrumentFormViewWidget
from hexrd.ui.calibration.calibration_runner import CalibrationRunner
from hexrd.ui.calibration.auto.powder_runner import PowderRunner
from hexrd.ui.calibration.hedm.calibration_runner import HEDMCalibrationRunner
from hexrd.ui.calibration.hkl_picks_tree_view_dialog import (
    HKLPicksTreeViewDialog, overlays_to_tree_format, tree_format_to_picks,
)
from hexrd.ui.calibration.structureless import StructurelessCalibrationRunner
from hexrd.ui.calibration.wppf_runner import WppfRunner
from hexrd.ui.create_polar_mask import (
    create_polar_mask_from_raw, rebuild_polar_masks
)
from hexrd.ui.create_raw_mask import (
    convert_polar_to_raw, create_raw_mask, rebuild_raw_masks)
from hexrd.ui.constants import ViewType, DOCUMENTATION_URL
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_calculator_dialog import ImageCalculatorDialog
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.llnl_import_tool_dialog import LLNLImportToolDialog
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui.simple_image_series_dialog import SimpleImageSeriesDialog
from hexrd.ui.pinhole_mask_dialog import PinholeMaskDialog
from hexrd.ui.pinhole_panel_buffer import generate_pinhole_panel_buffer
from hexrd.ui.polarization_options_dialog import (
    PolarizationOptionsDialog
)
from hexrd.ui.mask_manager_dialog import MaskManagerDialog
from hexrd.ui.mask_regions_dialog import MaskRegionsDialog
from hexrd.ui.materials_panel import MaterialsPanel
from hexrd.ui.messages_widget import MessagesWidget
from hexrd.ui.refinements_editor import RefinementsEditor
from hexrd.ui.save_images_dialog import SaveImagesDialog
from hexrd.ui.transform_dialog import TransformDialog
from hexrd.ui.indexing.indexing_tree_view_dialog import IndexingTreeViewDialog
from hexrd.ui.indexing.fit_grains_tree_view_dialog import (
    FitGrainsTreeViewDialog
)
from hexrd.ui.image_mode_widget import ImageModeWidget
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals, unique_name
from hexrd.ui.utils.dialog import add_help_url
from hexrd.ui.rerun_clustering_dialog import RerunClusteringDialog
from hexrd.ui import state


class MainWindow(QObject):

    # Emitted when new images are loaded
    new_images_loaded = Signal()

    # Emitted when a new mask is added
    new_mask_added = Signal(str)

    # Emitted when a new configuration is loaded
    config_loaded = Signal()

    def __init__(self, parent=None, image_files=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('main_window.ui', parent)
        self.confirm_application_close = True

        self.thread_pool = QThreadPool(self)
        self.progress_dialog = ProgressDialog(self.ui)
        self.progress_dialog.setWindowTitle('Calibration Running')

        self.messages_widget = MessagesWidget(self.ui)
        dock_widget_contents = self.ui.messages_dock_widget_contents
        dock_widget_contents.layout().addWidget(self.messages_widget.ui)
        self.ui.resizeDocks([self.ui.messages_dock_widget], [80], Qt.Vertical)

        # Let the left dock widget take up the whole left side
        self.ui.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        self.ui.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)

        self.color_map_editor = ColorMapEditor(self.ui.image_tab_widget,
                                               self.ui.central_widget)
        self.color_map_editor.hide_overlays_during_bc_editing = True
        self.ui.color_map_dock_widgets.layout().addWidget(
            self.color_map_editor.ui)

        self.image_mode_widget = ImageModeWidget(self.ui.central_widget)
        self.ui.image_mode_dock_widgets.layout().addWidget(
            self.image_mode_widget.ui)

        self.add_materials_panel()

        self.simple_image_series_dialog = SimpleImageSeriesDialog(self.ui)
        self.llnl_import_tool_dialog = LLNLImportToolDialog(
                                        self.color_map_editor, self.ui)
        self.image_stack_dialog = ImageStackDialog(
                                    self.ui, self.simple_image_series_dialog)

        self.cal_tree_view = CalTreeView(self.ui)
        self.instrument_form_view_widget = InstrumentFormViewWidget(self.ui)
        self.calibration_slider_widget = CalibrationSliderWidget(self.ui)

        tab_texts = ['Tree View', 'Form View', 'Slider View']
        self.ui.calibration_tab_widget.clear()
        self.ui.calibration_tab_widget.addTab(self.cal_tree_view,
                                              tab_texts[0])
        self.ui.calibration_tab_widget.addTab(
            self.instrument_form_view_widget.ui, tab_texts[1])
        self.ui.calibration_tab_widget.addTab(
            self.calibration_slider_widget.ui, tab_texts[2])

        url = 'configuration/instrument/'
        add_help_url(self.ui.config_button_box, url)

        self.mask_manager_dialog = MaskManagerDialog(self.ui)

        self._edit_colormap_list_dialog = EditColormapListDialog(
            self.ui, self.color_map_editor)

        self.setup_connections()

        self.update_config_gui()

        self.update_action_check_states()

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

    def setup_connections(self):
        """This is to setup connections for non-gui objects"""
        self.ui.installEventFilter(self)
        self.ui.action_open_config_file.triggered.connect(
            self.on_action_open_config_file_triggered)
        self.ui.action_open_grain_fitting_results.triggered.connect(
            self.open_grain_fitting_results)
        self.ui.action_save_config_yaml.triggered.connect(
            self.on_action_save_config_yaml_triggered)
        self.ui.action_save_config_hexrd.triggered.connect(
            self.on_action_save_config_hexrd_triggered)
        self.ui.action_open_materials.triggered.connect(
            self.on_action_open_materials_triggered)
        self.ui.action_save_imageseries.triggered.connect(
            self.on_action_save_imageseries_triggered)
        self.ui.action_save_materials.triggered.connect(
            self.on_action_save_materials_triggered)
        self.ui.action_save_state.triggered.connect(
            self.on_action_save_state_triggered)
        self.ui.action_open_state.triggered.connect(
            self.on_action_load_state_triggered)
        self.ui.action_export_current_plot.triggered.connect(
            self.on_action_export_current_plot_triggered)
        self.ui.action_export_to_maud.triggered.connect(
            self.on_action_export_to_maud_triggered)
        self.ui.action_edit_euler_angle_convention.triggered.connect(
            self.on_action_edit_euler_angle_convention)
        self.ui.action_edit_apply_hand_drawn_mask.triggered.connect(
            self.on_action_edit_apply_hand_drawn_mask_triggered)
        self.ui.action_edit_apply_hand_drawn_mask.triggered.connect(
            self.ui.image_tab_widget.toggle_off_toolbar)
        self.ui.action_edit_apply_laue_mask_to_polar.triggered.connect(
            self.on_action_edit_apply_laue_mask_to_polar_triggered)
        self.ui.action_edit_apply_powder_mask_to_polar.triggered.connect(
            self.action_edit_apply_powder_mask_to_polar)
        self.ui.action_edit_apply_region_mask.triggered.connect(
            self.on_action_edit_apply_region_mask_triggered)
        self.ui.action_edit_apply_pinhole_mask.triggered.connect(
            self.show_pinhole_mask_dialog)
        self.ui.action_edit_reset_instrument_config.triggered.connect(
            self.on_action_edit_reset_instrument_config)
        self.ui.action_edit_refinements.triggered.connect(
            self.edit_refinements)
        self.ui.action_transform_detectors.triggered.connect(
            self.on_action_transform_detectors_triggered)
        self.ui.action_image_calculator.triggered.connect(
            self.open_image_calculator)
        self.ui.action_open_mask_manager.triggered.connect(
            self.on_action_open_mask_manager_triggered)
        self.ui.action_show_live_updates.toggled.connect(
            self.set_live_update)
        self.ui.action_show_detector_borders.toggled.connect(
            HexrdConfig().set_show_detector_borders)
        self.ui.action_show_beam_marker.toggled.connect(
            self.show_beam_marker_toggled)
        self.ui.action_view_indexing_config.triggered.connect(
            self.view_indexing_config)
        self.ui.action_view_fit_grains_config.triggered.connect(
            self.view_fit_grains_config)
        self.ui.action_view_overlay_picks.triggered.connect(
            self.view_overlay_picks)
        self.ui.calibration_tab_widget.currentChanged.connect(
            self.update_config_gui)
        self.image_mode_widget.tab_changed.connect(self.change_image_mode)
        self.image_mode_widget.mask_applied.connect(self.update_all)
        self.ui.action_run_fast_powder_calibration.triggered.connect(
            self.start_fast_powder_calibration)
        self.ui.action_run_laue_and_powder_calibration.triggered.connect(
            self.on_action_run_laue_and_powder_calibration_triggered)
        self.ui.action_run_laue_and_powder_calibration.triggered.connect(
            self.ui.image_tab_widget.toggle_off_toolbar)
        self.ui.action_run_structureless_calibration.triggered.connect(
            self.run_structureless_calibration)
        self.ui.action_run_hedm_calibration.triggered.connect(
            self.run_hedm_calibration)
        self.ui.action_run_indexing.triggered.connect(
            self.on_action_run_indexing_triggered)
        self.ui.action_rerun_clustering.triggered.connect(
            self.on_action_rerun_clustering)
        self.ui.action_run_fit_grains.triggered.connect(
            self.on_action_run_fit_grains_triggered)
        self.ui.action_run_wppf.triggered.connect(self.run_wppf)
        self.new_images_loaded.connect(self.images_loaded)
        self.ui.image_tab_widget.update_needed.connect(self.update_all)
        self.ui.image_tab_widget.new_mouse_position.connect(
            self.new_mouse_position)
        self.ui.image_tab_widget.clear_mouse_position.connect(
            self.ui.status_bar.clearMessage)
        self.llnl_import_tool_dialog.new_config_loaded.connect(
            self.update_config_gui)
        self.llnl_import_tool_dialog.cancel_workflow.connect(
            self.load_dummy_images)
        self.config_loaded.connect(
            self.llnl_import_tool_dialog.config_loaded_from_menu)
        self.ui.action_show_toolbar.toggled.connect(
            self.ui.image_tab_widget.toggle_off_toolbar)
        self.ui.action_hedm_import_tool.triggered.connect(
            self.on_action_hedm_import_tool_triggered)
        self.ui.action_llnl_import_tool.triggered.connect(
            self.on_action_llnl_import_tool_triggered)
        self.ui.action_image_stack.triggered.connect(
            self.on_action_image_stack_triggered)
        self.ui.action_show_all_colormaps.triggered.connect(
            self.on_action_show_all_colormaps_toggled)
        self.ui.action_edit_defaults.triggered.connect(
            self.on_action_edit_defaults_toggled)

        self.image_mode_widget.polar_show_snip1d.connect(
            self.ui.image_tab_widget.polar_show_snip1d)

        self.ui.action_open_images.triggered.connect(
            self.open_image_files)
        HexrdConfig().update_status_bar.connect(
            self.ui.status_bar.showMessage)
        HexrdConfig().detectors_changed.connect(
            self.on_detectors_changed)
        HexrdConfig().detector_shape_changed.connect(
            self.on_detector_shape_changed)
        HexrdConfig().deep_rerender_needed.connect(self.deep_rerender)
        HexrdConfig().rerender_needed.connect(self.on_rerender_needed)
        HexrdConfig().raw_masks_changed.connect(self.update_all)

        ImageLoadManager().update_needed.connect(self.update_all)
        ImageLoadManager().new_images_loaded.connect(self.new_images_loaded)
        ImageLoadManager().images_transformed.connect(self.update_config_gui)
        ImageLoadManager().live_update_status.connect(self.set_live_update)
        ImageLoadManager().state_updated.connect(
            self.simple_image_series_dialog.setup_gui)

        self.new_mask_added.connect(self.mask_manager_dialog.update_masks_list)
        self.image_mode_widget.tab_changed.connect(
            self.mask_manager_dialog.image_mode_changed)

        self.ui.action_apply_pixel_solid_angle_correction.toggled.connect(
            HexrdConfig().set_apply_pixel_solid_angle_correction)
        self.ui.action_apply_polarization_correction.toggled.connect(
            self.apply_polarization_correction_toggled)
        self.ui.action_apply_lorentz_correction.toggled.connect(
            self.apply_lorentz_correction_toggled)
        self.ui.action_subtract_minimum.toggled.connect(
            HexrdConfig().set_intensity_subtract_minimum)

        HexrdConfig().instrument_config_loaded.connect(self.update_config_gui)
        HexrdConfig().state_loaded.connect(self.on_state_loaded)
        HexrdConfig().image_view_loaded.connect(self.on_image_view_loaded)

        self.ui.action_about.triggered.connect(self.on_action_about_triggered)
        self.ui.action_documentation.triggered.connect(
            self.on_action_documentation_triggered)

        # Update menu item tooltips when their enable state changes
        for widget_name in self._menu_item_tooltips:
            w = getattr(self.ui, widget_name)
            w.changed.connect(self._update_menu_item_tooltip_for_sender)

        HexrdConfig().enable_canvas_focus_mode.connect(
            self.enable_canvas_focus_mode)

    def on_state_loaded(self):
        self.update_action_check_states()

    def update_action_check_states(self):
        checkbox_to_hexrd_config_mappings = {
            'action_apply_pixel_solid_angle_correction':
                'apply_pixel_solid_angle_correction',
            'action_apply_polarization_correction':
                'apply_polarization_correction',
            'action_apply_lorentz_correction': 'apply_lorentz_correction',
            'action_subtract_minimum': 'intensity_subtract_minimum',
            'action_show_live_updates': 'live_update',
            'action_show_detector_borders': 'show_detector_borders',
            'action_show_beam_marker': 'show_beam_marker',
            'action_show_all_colormaps': 'show_all_colormaps',
        }

        for cb_name, attr_name in checkbox_to_hexrd_config_mappings.items():
            cb = getattr(self.ui, cb_name)
            with block_signals(cb):
                cb.setChecked(getattr(HexrdConfig(), attr_name))

    def set_icon(self, icon):
        self.ui.setWindowIcon(icon)

    def show(self):
        self.ui.show()

    def add_materials_panel(self):
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
        self.ui.config_tool_box.insertItem(materials_panel_index,
                                           self.materials_panel.ui,
                                           'Materials')

    def enable_canvas_focus_mode(self, b):
        # Disable these widgets when focus mode is set
        disable_widgets = [
            self.image_mode_widget.ui,
            self.ui.config_tool_box,
            self.ui.menu_bar,
        ]
        for w in disable_widgets:
            w.setEnabled(not b)

    def on_action_open_config_file_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Configuration', HexrdConfig().working_dir,
            'HEXRD files (*.hexrd *.yml)')

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)

            HexrdConfig().load_instrument_config(str(path))

    def _save_config(self, extension, filter):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Configuration', HexrdConfig().working_dir, filter)

        if selected_file:
            if Path(selected_file).suffix != extension:
                selected_file += extension

            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return HexrdConfig().save_instrument_config(selected_file)

    def on_action_save_config_hexrd_triggered(self):
        self._save_config('.hexrd', 'HEXRD files (*.hexrd)')

    def on_action_save_config_yaml_triggered(self):
        self._save_config('.yml', 'YAML files (*.yml)')

    def open_grain_fitting_results(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Open Grain Fitting File', HexrdConfig().working_dir,
            'Grain fitting output files (*.out)')

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)

            data = np.loadtxt(selected_file, ndmin=2)
            dialog = FitGrainsResultsDialog(
                data, parent=self.ui, allow_export_workflow=False)
            dialog.show()
            self._fit_grains_results_dialog = dialog

    def on_detectors_changed(self):
        HexrdConfig().clear_overlay_data()
        HexrdConfig().current_imageseries_idx = 0
        self.load_dummy_images()
        self.ui.image_tab_widget.switch_toolbar(0)
        self.simple_image_series_dialog.config_changed()

    def on_detector_shape_changed(self, det_key):
        # We need to load/reset the dummy images if a detector's shape changes.
        # Otherwise, the HexrdConfig().images_dict object will not have images
        # with the correct shape.
        self.load_dummy_images()

    def load_dummy_images(self):
        if HexrdConfig().loading_state:
            # Don't load the dummy images during state load
            return

        ImageFileManager().load_dummy_images()
        self.update_all(clear_canvases=True)
        self.ui.action_transform_detectors.setEnabled(False)
        self.new_images_loaded.emit()

    def open_image_file(self):
        images_dir = HexrdConfig().images_dir

        selected_file, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, dir=images_dir)

        if len(selected_file) > 1:
            msg = ('Please select only one file.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        return selected_file

    def open_image_files(self):
        # Get the most recent images dir
        images_dir = HexrdConfig().images_dir

        selected_files, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, dir=images_dir)

        if selected_files:
            # Save the chosen dir
            HexrdConfig().set_images_dir(selected_files[0])

            files, manual = ImageLoadManager().load_images(selected_files)
            if not files:
                return

            if (any(len(f) != 1 for f in files)
                    or len(files) < len(HexrdConfig().detector_names)):
                msg = ('Number of files must match number of detectors: ' +
                       str(len(HexrdConfig().detector_names)))
                QMessageBox.warning(self.ui, 'HEXRD', msg)
                return

            # If it is a hdf5 file allow the user to select the path
            ext = os.path.splitext(selected_files[0])[1]
            if (ImageFileManager().is_hdf(ext) and not
                    ImageFileManager().hdf_path_exists(selected_files[0])):

                selection = ImageFileManager().path_prompt(selected_files[0])
                if not selection:
                    return

            dialog = LoadImagesDialog(files, manual, self.ui)

            if dialog.exec_():
                detector_names, image_files = dialog.results()
                image_files = [img for f in files for img in f]
                files = [[] for det in HexrdConfig().detector_names]
                for d, f in zip(detector_names, image_files):
                    pos = HexrdConfig().detector_names.index(d)
                    files[pos].append(f)
                HexrdConfig().recent_images = image_files
                ImageLoadManager().read_data(files, ui_parent=self.ui)

    def images_loaded(self, enabled=True):
        self.ui.action_transform_detectors.setEnabled(enabled)
        self.update_color_map_bounds()
        self.update_enable_states()
        self.color_map_editor.reset_range()
        self.image_mode_widget.reset_masking()
        self.update_image_mode_enable_states()

    def on_action_open_materials_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Materials File', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            HexrdConfig().load_materials(selected_file)

    def on_action_save_imageseries_triggered(self):
        if not HexrdConfig().has_images:
            msg = ('No ImageSeries available for saving.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        SaveImagesDialog(self.ui).exec_()

    def on_action_save_materials_triggered(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Materials', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)

            # Ensure the file name has an hdf5 ending
            acceptable_exts = ['.h5', '.hdf5']
            if not any(selected_file.endswith(x) for x in acceptable_exts):
                selected_file += '.h5'

            return HexrdConfig().save_materials(selected_file)

    def on_action_export_current_plot_triggered(self):
        filters = 'HDF5 files (*.h5 *.hdf5);; NPZ files (*.npz)'
        if self.image_mode == ViewType.polar:
            # We can do CSV and XY as well
            filters += ';; CSV files (*.csv);; XY files (*.xy)'

        default_name = f'{self.image_mode}_view.h5'
        default_path = os.path.join(HexrdConfig().working_dir, default_name)
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Current View', default_path, filters)

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            return self.ui.image_tab_widget.export_current_plot(selected_file)

    def on_action_export_to_maud_triggered(self):
        filters = 'ESG files (*.esg)'

        default_path = os.path.join(HexrdConfig().working_dir, "maud.esg")
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export to Maud', default_path, filters)

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            return self.ui.image_tab_widget.export_to_maud(selected_file)

    def on_action_run_laue_and_powder_calibration_triggered(self):
        if not hasattr(self, '_calibration_runner_async_runner'):
            # Initialize this only once and keep it around, so we don't
            # run into issues connecting/disconnecting the messages.
            self._calibration_runner_async_runner = AsyncRunner(self.ui)

        async_runner = self._calibration_runner_async_runner
        canvas = self.ui.image_tab_widget.image_canvases[0]
        runner = CalibrationRunner(canvas, async_runner)
        self._calibration_runner = runner
        runner.finished.connect(self.calibration_finished)

        try:
            runner.run()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            raise

    def calibration_finished(self):
        print('Calibration finished')
        print('Updating the GUI')
        self.update_config_gui()
        self.deep_rerender()

    def run_structureless_calibration(self):
        cached_async_runner_name = '_structureless_calibration_async_runner'
        if not hasattr(self, cached_async_runner_name):
            # Initialize this only once and keep it around, so we don't
            # run into issues connecting/disconnecting the messages.
            setattr(self, cached_async_runner_name, AsyncRunner(self.ui))

        async_runner = getattr(self, cached_async_runner_name)

        canvas = self.ui.image_tab_widget.image_canvases[0]
        runner = StructurelessCalibrationRunner(canvas, async_runner, self.ui)
        runner.instrument_updated.connect(
            self.structureless_calibration_updated)

        try:
            runner.run()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            raise

    def structureless_calibration_updated(self):
        self.update_config_gui()
        self.update_all()

    def run_hedm_calibration(self):
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

    def on_hedm_calibration_finished(self):
        self.update_config_gui()
        self.deep_rerender()

    def on_action_run_indexing_triggered(self):
        self.ui.action_rerun_clustering.setEnabled(False)
        self._indexing_runner = IndexingRunner(self.ui)
        self._indexing_runner.clustering_ran.connect(
            self.ui.action_rerun_clustering.setEnabled)
        self._indexing_runner.run()

    def on_action_rerun_clustering(self):
        RerunClusteringDialog(self._indexing_runner, self.ui).exec_()

    def on_action_run_fit_grains_triggered(self):
        kwargs = {
            'grains_table': None,
            'indexing_runner': getattr(self, '_indexing_runner', None),
            'started_from_indexing': False,
            'parent': self.ui,
        }
        runner = self._grain_fitting_runner = FitGrainsRunner(**kwargs)
        runner.run()

    def run_wppf(self):
        self._wppf_runner = WppfRunner(self.ui)
        try:
            self._wppf_runner.run()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            raise

    def update_color_map_bounds(self):
        self.color_map_editor.update_bounds(HexrdConfig().images_dict)

    def on_action_edit_euler_angle_convention(self):
        allowed_conventions = [
            'None',
            'Extrinsic XYZ',
            'Intrinsic ZXZ'
        ]
        corresponding_values = [
            None,
            {
                'axes_order': 'xyz',
                'extrinsic': True
            },
            {
                'axes_order': 'zxz',
                'extrinsic': False
            }
        ]
        current = HexrdConfig().euler_angle_convention
        ind = corresponding_values.index(current)

        help_url = 'configuration/instrument/#euler-angle-convention'
        name, ok = InputDialog.getItem(self.ui, 'HEXRD',
                                       'Select Euler Angle Convention',
                                       allowed_conventions, ind, False,
                                       help_url=help_url)

        if not ok:
            # User canceled...
            return

        chosen = corresponding_values[allowed_conventions.index(name)]
        HexrdConfig().set_euler_angle_convention(chosen)

        self.update_all()
        self.update_config_gui()

    def on_action_edit_apply_hand_drawn_mask_triggered(self):
        # Make the dialog
        canvas = self.ui.image_tab_widget.image_canvases[0]
        self._apply_drawn_mask_line_picker = (
            HandDrawnMaskDialog(canvas, self.ui))
        self._apply_drawn_mask_line_picker.start()
        self._apply_drawn_mask_line_picker.finished.connect(
            self.run_apply_hand_drawn_mask)

    def run_apply_hand_drawn_mask(self, dets, line_data):
        if self.image_mode == ViewType.polar:
            for line in line_data:
                name = unique_name(
                    HexrdConfig().raw_mask_coords, 'polar_mask_0')
                raw_line = convert_polar_to_raw([line])
                HexrdConfig().raw_mask_coords[name] = raw_line
                HexrdConfig().visible_masks.append(name)
                create_polar_mask_from_raw(name, raw_line)
            HexrdConfig().polar_masks_changed.emit()
        elif self.image_mode == ViewType.raw:
            for det, line in zip(dets, line_data):
                name = unique_name(
                    HexrdConfig().raw_mask_coords, 'raw_mask_0')
                HexrdConfig().raw_mask_coords[name] = [(det, line.copy())]
                HexrdConfig().visible_masks.append(name)
                create_raw_mask(name, [(det, line)])
            HexrdConfig().raw_masks_changed.emit()
        self.new_mask_added.emit(self.image_mode)

    def on_action_edit_apply_laue_mask_to_polar_triggered(self):
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

        name = unique_name(HexrdConfig().raw_mask_coords, 'laue_mask')
        raw_data = convert_polar_to_raw(data)
        HexrdConfig().raw_mask_coords[name] = raw_data
        create_polar_mask_from_raw(name, raw_data)
        HexrdConfig().visible_masks.append(name)
        self.new_mask_added.emit(self.image_mode)
        HexrdConfig().polar_masks_changed.emit()

    def action_edit_apply_powder_mask_to_polar(self):
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
                a = iter(val['rbnds'])
                for start, end in zip(a, a):
                    ranges = np.array(np.flip(start, axis=1))
                    ranges = np.append(ranges, np.flip(end), axis=0)
                    ranges = np.append(ranges, [ranges[0]], axis=0)
                    data.append(ranges[~np.isnan(ranges).any(axis=1)])

        if not data:
            msg = 'No powder overlay ranges found'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        name = unique_name(HexrdConfig().raw_mask_coords, 'powder_mask')
        raw_data = convert_polar_to_raw(data)
        HexrdConfig().raw_mask_coords[name] = raw_data
        create_polar_mask_from_raw(name, raw_data)
        HexrdConfig().visible_masks.append(name)
        self.new_mask_added.emit(self.image_mode)
        HexrdConfig().polar_masks_changed.emit()

    def on_action_edit_apply_region_mask_triggered(self):
        mrd = MaskRegionsDialog(self.ui)
        mrd.new_mask_added.connect(self.new_mask_added.emit)
        mrd.show()

        self.ui.image_tab_widget.toggle_off_toolbar()

    def show_pinhole_mask_dialog(self):
        if not hasattr(self, '_pinhole_mask_dialog'):
            self._pinhole_mask_dialog = PinholeMaskDialog(self.ui)
            self._pinhole_mask_dialog.apply_clicked.connect(
                self.apply_pinhole_mask)

        self._pinhole_mask_dialog.show()

    def apply_pinhole_mask(self, radius, thickness):
        kwargs = {
            'instr': create_hedm_instrument(),
            'pinhole_radius': radius,
            'pinhole_thickness': thickness,
        }
        ph_buffer = generate_pinhole_panel_buffer(**kwargs)

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
        HexrdConfig().raw_mask_coords[name] = ph_masks
        if name not in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.append(name)

        HexrdConfig().raw_masks_changed.emit()

        self.new_mask_added.emit(self.image_mode)

    def on_action_edit_reset_instrument_config(self):
        HexrdConfig().restore_instrument_config_backup()
        self.update_config_gui()

    def edit_refinements(self):
        w = self._refinements_editor = RefinementsEditor(self.ui)
        if not w.ui.exec_():
            return

        # Update the UI in case settings have changed
        self.update_config_gui()
        self.materials_panel.update_overlay_editor()

        if w.material_values_modified:
            HexrdConfig().active_material_modified.emit()

        update_canvas = w.iconfig_values_modified or w.material_values_modified
        if update_canvas:
            self.deep_rerender()

    def change_image_mode(self, mode):
        self.image_mode = mode
        self.update_image_mode_enable_states()

        # Clear the overlays
        HexrdConfig().clear_overlay_data()

        self.update_all()

    def update_image_mode_enable_states(self):
        # This is for enable states that depend on the image mode
        is_cartesian = self.image_mode == ViewType.cartesian
        is_polar = self.image_mode == ViewType.polar
        is_raw = self.image_mode == ViewType.raw
        is_stereo = self.image_mode == ViewType.stereo

        has_images = HexrdConfig().has_images

        self.ui.action_export_current_plot.setEnabled(
            (is_polar or is_cartesian or is_stereo) and has_images)
        self.ui.action_run_laue_and_powder_calibration.setEnabled(
            is_polar and has_images)
        self.ui.action_run_structureless_calibration.setEnabled(
            is_polar and has_images)
        self.ui.action_edit_apply_hand_drawn_mask.setEnabled(
            (is_polar or is_raw) and has_images)
        self.ui.action_run_wppf.setEnabled(is_polar and has_images)
        self.ui.action_edit_apply_laue_mask_to_polar.setEnabled(is_polar)
        self.ui.action_edit_apply_powder_mask_to_polar.setEnabled(is_polar)
        self.ui.action_export_to_maud.setEnabled(is_polar and has_images)

    def start_fast_powder_calibration(self):
        if not HexrdConfig().has_images:
            msg = ('No images available for calibration.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        if hasattr(self, '_powder_runner'):
            self._powder_runner.clear()

        self._powder_runner = PowderRunner(self.ui)
        self._powder_runner.finished.connect(self.finish_powder_calibration)
        self._powder_runner.run()

    def finish_powder_calibration(self):
        self.update_config_gui()
        self.deep_rerender()

    def update_config_gui(self):
        current_widget = self.ui.calibration_tab_widget.currentWidget()
        if current_widget is self.cal_tree_view:
            self.cal_tree_view.rebuild_tree()
        elif current_widget is self.instrument_form_view_widget.ui:
            self.instrument_form_view_widget.update_gui_from_config()
        elif current_widget is self.calibration_slider_widget.ui:
            self.calibration_slider_widget.update_gui_from_config()
        self.config_loaded.emit()

    def eventFilter(self, target, event):
        if type(target) == QMainWindow and event.type() == QEvent.Close:
            if self.confirm_application_close:
                msg = 'Are you sure you want to quit?'
                response = QMessageBox.question(self.ui, 'HEXRD', msg)
                if response == QMessageBox.No:
                    event.ignore()
                    return True
            # If the main window is closing, save the config settings
            HexrdConfig().save_settings()

        if not hasattr(self, '_first_paint_occurred'):
            if type(target) == QMainWindow and event.type() == QEvent.Paint:
                # Draw the images for the first time after the first paint
                # has occurred in order to avoid a black window.
                QTimer.singleShot(0, self.update_all)
                self._first_paint_occurred = True

        return False

    def update_if_mode_matches(self, mode):
        if self.image_mode == mode:
            self.update_all()

    def deep_rerender(self):
        # Clear all overlays
        HexrdConfig().clear_overlay_data()

        # Update all and clear the canvases
        self.update_all(clear_canvases=True)

    def update_all(self, clear_canvases=False):
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
        if QApplication.focusWidget() is not None:
            QApplication.focusWidget().clearFocus()

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

    def set_live_update(self, enabled):
        HexrdConfig().live_update = enabled

        if enabled:
            # Go ahead and trigger an update as well
            self.update_all()

    def on_rerender_needed(self):
        # Only perform an update if we have live updates enabled
        if HexrdConfig().live_update:
            self.update_all()

    def show_beam_marker_toggled(self, b):
        HexrdConfig().show_beam_marker = b
        if b:
            # Also show the style editor dialog
            if not hasattr(self, '_beam_marker_style_editor'):
                self._beam_marker_style_editor = BeamMarkerStyleEditor(self.ui)

            self._beam_marker_style_editor.show()

    def view_indexing_config(self):
        if hasattr(self, '_indexing_config_view'):
            self._indexing_config_view.reject()

        view = self._indexing_config_view = IndexingTreeViewDialog(self.ui)
        view.show()

    def view_fit_grains_config(self):
        if hasattr(self, '_fit_grains_config_view'):
            self._fit_grains_config_view.reject()

        view = self._fit_grains_config_view = FitGrainsTreeViewDialog(self.ui)
        view.show()

    def view_overlay_picks(self):
        # Only works in the polar view right now, but could in theory work in
        # other views.
        if self.image_mode != ViewType.polar:
            msg = (
                'Overlay picks may currently only be viewed in the polar '
                'image mode'
            )
            print(msg)
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        canvas = self.ui.image_tab_widget.image_canvases[0]

        overlays = HexrdConfig().overlays

        # Pad all of the overlays to make sure their data is updated
        for overlay in overlays:
            overlay.pad_picks_data()

        kwargs = {
            'dictionary': overlays_to_tree_format(overlays),
            'coords_type': ViewType.polar,
            'canvas': canvas,
            'parent': canvas,
        }
        dialog = HKLPicksTreeViewDialog(**kwargs)
        dialog.button_box_visible = True
        dialog.ui.show()

        def remove_all_highlighting():
            for overlay in overlays:
                overlay.clear_highlights()
            HexrdConfig().flag_overlay_updates_for_all_materials()
            HexrdConfig().overlay_config_changed.emit()

        def on_accepted():
            # Write the modified picks to the overlays
            updated_picks = tree_format_to_picks(dialog.dictionary)
            for i, new_picks in enumerate(updated_picks):
                overlays[i].calibration_picks_polar = new_picks['picks']

        def on_finished():
            remove_all_highlighting()

        dialog.ui.accepted.connect(on_accepted)
        dialog.ui.finished.connect(on_finished)

    def new_mouse_position(self, info):
        if self.image_mode == ViewType.polar:
            # Use a special function for polar
            labels = self.polar_mouse_info_labels(info)
        else:
            labels = self.default_mouse_info_labels(info)

        delimiter = ',  '
        msg = delimiter.join(labels)
        self.ui.status_bar.showMessage(msg)

    def default_mouse_info_labels(self, info):
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
            labels.append(f'Q = {info["Q"]:8.3f}')
            labels.append(f'hkl ({material_name}) = {info["hkl"]}')

        return labels

    def polar_mouse_info_labels(self, info):
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
            labels.append(f'Q = {info["Q"]:8.3f}')
            labels.append(f'hkl ({material_name}) = {info["hkl"]}')

        return labels

    def on_action_transform_detectors_triggered(self):
        mask_state = HexrdConfig().threshold_mask_status
        self.image_mode_widget.reset_masking()
        _ = TransformDialog(self.ui).exec_()
        self.image_mode_widget.reset_masking(mask_state)

    def open_image_calculator(self):
        if dialog := getattr(self, '_image_calculator_dialog', None):
            dialog.hide()

        dialog = ImageCalculatorDialog(HexrdConfig().images_dict, self.ui)
        dialog.show()
        self._image_calculator_dialog = dialog

        def on_accepted():
            ims = dialog.calculate()

            # Replace the current image series with this one
            HexrdConfig().imageseries_dict[dialog.detector] = ims

            # Rerender
            self.update_all()

        dialog.accepted.connect(on_accepted)

    def update_enable_states(self):
        has_images = HexrdConfig().has_images
        num_images = HexrdConfig().imageseries_length

        enable_image_calculator = has_images and num_images == 1
        self.ui.action_image_calculator.setEnabled(enable_image_calculator)

        # Update the HEDM enable states
        self.update_hedm_enable_states()

    def update_hedm_enable_states(self):
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
    def image_mode(self):
        return HexrdConfig().image_mode

    @image_mode.setter
    def image_mode(self, b):
        HexrdConfig().image_mode = b

    @property
    def _menu_item_tooltips(self):
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
                False: ('Cartesian/polar/stereo view must be active '
                        'with image data loaded'),
            },
            'action_export_to_maud': {
                True: '',
                False: 'Polar view must be active with image data loaded',
            },
            'action_image_calculator': {
                True: '',
                False: ('Image data must be loaded (and must not be an image '
                        'stack)'),
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

    def _update_menu_item_tooltip_for_sender(self):
        # This function should be called automatically when the sending
        # QAction is modified.
        # The modification may have been its enable state.

        w = self.sender()
        enabled = w.isEnabled()
        name = w.objectName()

        tooltips = self._menu_item_tooltips
        if name not in tooltips:
            return

        w.setToolTip(tooltips[name][enabled])

    def update_all_menu_item_tooltips(self):
        tooltips = self._menu_item_tooltips

        for widget_name, tooltip_options in tooltips.items():
            w = getattr(self.ui, widget_name)
            enabled = w.isEnabled()
            w.setToolTip(tooltip_options[enabled])

    def on_action_open_mask_manager_triggered(self):
        self.mask_manager_dialog.show()

    def on_action_save_state_triggered(self):

        selected_file, _ = QFileDialog.getSaveFileName(
            self.ui, 'Save Current State', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

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
            try:
                h5_file = h5py.File(selected_file, 'r')
                state.load_imageseries_dict(h5_file)
            finally:
                HexrdConfig().loading_state = False

            # Perform a deep rerender so updates are reflected
            HexrdConfig().deep_rerender_needed.emit()

        HexrdConfig().working_dir = os.path.dirname(selected_file)

    def load_entrypoint_file(self, filepath):
        # First, identify what type of entrypoint file it is, and then
        # load based upon whatever it is.

        filepath = Path(filepath)
        if filepath.suffix in ('.yml', '.hexrd'):
            # It is an instrument file
            return HexrdConfig().load_instrument_config(str(filepath))

        # Assume it is a state file
        return self.load_state_file(filepath)

    def on_action_load_state_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load State', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            return

        path = Path(selected_file)
        HexrdConfig().working_dir = str(path.parent)

        self.load_state_file(selected_file)

    def load_state_file(self, filepath):
        # Some older state files have issues that need to be resolved.
        # Perform an update, if needed, to fix them, before reading.
        state.update_if_needed(filepath)

        # The image series will take care of closing the file
        h5_file = h5py.File(filepath, "r")
        try:
            state.load(h5_file)
        except Exception:
            # If an exception occurred, assume we should close the file...
            h5_file.close()
            raise

        # Since statuses are added after the instrument config is loaded,
        # the statuses in the GUI might not be up to date. Ensure it is.
        self.update_config_gui()

    def add_view_dock_widget_actions(self):
        # Add actions to show/hide all of the dock widgets
        dock_widgets = self.ui.findChildren(QDockWidget)
        titles = [w.windowTitle() for w in dock_widgets]
        for title, w in sorted(zip(titles, dock_widgets)):
            self.ui.view_dock_widgets.addAction(w.toggleViewAction())

    def apply_polarization_correction_toggled(self, b):
        if not b:
            # Just turn it off and return
            HexrdConfig().apply_polarization_correction = b
            return

        # Get the user to first select the Lorentz polarization options
        d = PolarizationOptionsDialog(self.ui)
        if not d.exec_():
            # Canceled... uncheck the action.
            action = self.ui.action_apply_polarization_correction
            action.setChecked(False)
            return

        # The dialog should have modified HexrdConfig's polarization
        # options already. Just apply it now.
        HexrdConfig().apply_polarization_correction = b

    def apply_lorentz_correction_toggled(self, b):
        HexrdConfig().apply_lorentz_correction = b

    def on_action_hedm_import_tool_triggered(self):
        self.simple_image_series_dialog.show()

    def on_action_llnl_import_tool_triggered(self):
        self.llnl_import_tool_dialog.show()

    def on_action_image_stack_triggered(self):
        self.image_stack_dialog.show()

    def on_image_view_loaded(self, images):
        # Update the data, but don't reset the bounds
        # This will update the histogram in the B&C editor
        self.color_map_editor.data = images

    def on_action_about_triggered(self):
        dialog = AboutDialog(self.ui)
        dialog.ui.exec_()

    def on_action_documentation_triggered(self):
        QDesktopServices.openUrl(QUrl(DOCUMENTATION_URL))

    def on_action_show_all_colormaps_toggled(self, checked):
        HexrdConfig().show_all_colormaps = checked
        self.color_map_editor.load_cmaps()

    def on_action_edit_defaults_toggled(self):
        self._edit_colormap_list_dialog.show()
