import os
from pathlib import Path
import tempfile

import h5py
from hexrd.ui.image_stack_dialog import ImageStackDialog
import numpy as np

from PySide2.QtCore import QEvent, QObject, Qt, QThreadPool, Signal, QTimer
from PySide2.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QInputDialog, QMainWindow,
    QMessageBox
)

from hexrd.ui.async_runner import AsyncRunner
from hexrd.ui.calibration_config_widget import CalibrationConfigWidget
from hexrd.ui.calibration_slider_widget import CalibrationSliderWidget

from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.progress_dialog import ProgressDialog
from hexrd.ui.cal_tree_view import CalTreeView
from hexrd.ui.hand_drawn_mask_dialog import HandDrawnMaskDialog
from hexrd.ui.indexing.run import FitGrainsRunner, IndexingRunner
from hexrd.ui.indexing.fit_grains_results_dialog import FitGrainsResultsDialog
from hexrd.ui.calibration.calibration_runner import CalibrationRunner
from hexrd.ui.calibration.auto.powder_runner import PowderRunner
from hexrd.ui.calibration.wppf_runner import WppfRunner
from hexrd.ui.create_polar_mask import create_polar_mask, rebuild_polar_masks
from hexrd.ui.create_raw_mask import (
    convert_polar_to_raw, create_raw_mask, rebuild_raw_masks)
from hexrd.ui.utils import unique_name
from hexrd.ui.constants import (
    OverlayType, ViewType, WORKFLOW_HEDM, WORKFLOW_LLNL)
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.llnl_import_tool_dialog import LLNLImportToolDialog
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui.simple_image_series_dialog import SimpleImageSeriesDialog
from hexrd.ui.lorentz_polarization_options_dialog import (
    LorentzPolarizationOptionsDialog
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
        self.workflow_widgets = {'HEDM': [], 'LLNL': []}

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
        self.ui.color_map_dock_widgets.layout().addWidget(
            self.color_map_editor.ui)

        self.image_mode = ViewType.raw
        self.image_mode_widget = ImageModeWidget(self.ui.central_widget)
        self.ui.image_mode_dock_widgets.layout().addWidget(
            self.image_mode_widget.ui)

        self.add_materials_panel()

        self.load_widget = SimpleImageSeriesDialog(self.ui)
        self.import_data_widget = LLNLImportToolDialog(self.color_map_editor,
                                                  self.ui)

        self.cal_tree_view = CalTreeView(self.ui)
        self.calibration_config_widget = CalibrationConfigWidget(self.ui)
        self.calibration_slider_widget = CalibrationSliderWidget(self.ui)

        tab_texts = ['Tree View', 'Form View', 'Slider View']
        self.ui.calibration_tab_widget.clear()
        self.ui.calibration_tab_widget.addTab(self.cal_tree_view,
                                              tab_texts[0])
        self.ui.calibration_tab_widget.addTab(
            self.calibration_config_widget.ui, tab_texts[1])
        self.ui.calibration_tab_widget.addTab(
            self.calibration_slider_widget.ui, tab_texts[2])

        self.mask_manager_dialog = MaskManagerDialog(self.ui)

        self.setup_connections()

        self.update_config_gui()

        self.ui.action_apply_pixel_solid_angle_correction.setChecked(
            HexrdConfig().apply_pixel_solid_angle_correction)
        self.ui.action_apply_lorentz_polarization_correction.setChecked(
            HexrdConfig().apply_lorentz_polarization_correction)
        self.ui.action_subtract_minimum.setChecked(
            HexrdConfig().intensity_subtract_minimum)

        self.ui.action_show_live_updates.setChecked(HexrdConfig().live_update)
        self.live_update(HexrdConfig().live_update)

        ImageFileManager().load_dummy_images(True)

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
        self.ui.action_edit_apply_polygon_mask.triggered.connect(
            self.on_action_edit_apply_polygon_mask_triggered)
        self.ui.action_edit_apply_polygon_mask.triggered.connect(
            self.ui.image_tab_widget.toggle_off_toolbar)
        self.ui.action_edit_reset_instrument_config.triggered.connect(
            self.on_action_edit_reset_instrument_config)
        self.ui.action_edit_refinements.triggered.connect(
            self.edit_refinements)
        self.ui.action_transform_detectors.triggered.connect(
            self.on_action_transform_detectors_triggered)
        self.ui.action_open_mask_manager.triggered.connect(
            self.on_action_open_mask_manager_triggered)
        self.ui.action_show_live_updates.toggled.connect(
            self.live_update)
        self.ui.action_show_detector_borders.toggled.connect(
            HexrdConfig().set_show_detector_borders)
        self.ui.action_view_indexing_config.triggered.connect(
            self.view_indexing_config)
        self.ui.action_view_fit_grains_config.triggered.connect(
            self.view_fit_grains_config)
        self.ui.calibration_tab_widget.currentChanged.connect(
            self.update_config_gui)
        self.image_mode_widget.tab_changed.connect(self.change_image_mode)
        self.image_mode_widget.mask_applied.connect(self.update_all)
        self.ui.action_run_powder_calibration.triggered.connect(
            self.start_powder_calibration)
        self.ui.action_run_calibration.triggered.connect(
            self.on_action_run_calibration_triggered)
        self.ui.action_run_calibration.triggered.connect(
            self.ui.image_tab_widget.toggle_off_toolbar)
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
        self.import_data_widget.new_config_loaded.connect(
            self.update_config_gui)
        self.import_data_widget.cancel_workflow.connect(
            self.load_dummy_images)
        self.config_loaded.connect(
            self.import_data_widget.config_loaded_from_menu)
        self.ui.action_show_toolbar.toggled.connect(
            self.ui.image_tab_widget.toggle_off_toolbar)
        self.ui.action_hedm_import_tool.triggered.connect(
            self.on_action_hedm_import_tool_triggered)
        self.ui.action_llnl_import_tool.triggered.connect(
            self.on_action_llnl_import_tool_triggered)
        self.ui.action_image_stack.triggered.connect(
            self.on_action_image_stack_triggered)

        self.image_mode_widget.polar_show_snip1d.connect(
            self.ui.image_tab_widget.polar_show_snip1d)

        self.ui.action_open_images.triggered.connect(
            self.open_image_files)
        self.ui.action_open_aps_imageseries.triggered.connect(
            self.open_aps_imageseries)
        HexrdConfig().update_status_bar.connect(
            self.ui.status_bar.showMessage)
        HexrdConfig().detectors_changed.connect(
            self.on_detectors_changed)
        HexrdConfig().deep_rerender_needed.connect(self.deep_rerender)
        HexrdConfig().raw_masks_changed.connect(
            self.ui.image_tab_widget.load_images)

        ImageLoadManager().update_needed.connect(self.update_all)
        ImageLoadManager().new_images_loaded.connect(self.new_images_loaded)
        ImageLoadManager().images_transformed.connect(self.update_config_gui)
        ImageLoadManager().live_update_status.connect(self.live_update)
        ImageLoadManager().state_updated.connect(self.load_widget.setup_gui)

        self.new_mask_added.connect(self.mask_manager_dialog.update_masks_list)
        self.image_mode_widget.tab_changed.connect(
            self.mask_manager_dialog.image_mode_changed)

        HexrdConfig().calibration_complete.connect(self.calibration_finished)

        self.ui.action_apply_pixel_solid_angle_correction.toggled.connect(
            HexrdConfig().set_apply_pixel_solid_angle_correction)
        self.ui.action_apply_lorentz_polarization_correction.toggled.connect(
            self.apply_lorentz_polarization_correction_toggled)
        self.ui.action_subtract_minimum.toggled.connect(
            HexrdConfig().set_intensity_subtract_minimum)

        self.import_data_widget.enforce_raw_mode.connect(
            self.enforce_view_mode)

        HexrdConfig().instrument_config_loaded.connect(self.update_config_gui)

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
            dialog = FitGrainsResultsDialog(data, parent=self.ui)
            dialog.show()
            self._fit_grains_results_dialog = dialog

    def on_detectors_changed(self):
        HexrdConfig().clear_overlay_data()
        HexrdConfig().current_imageseries_idx = 0
        self.load_dummy_images()
        self.ui.image_tab_widget.switch_toolbar(0)
        self.load_widget.config_changed()

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
                    ImageFileManager().path_exists(selected_files[0])):

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
                ImageLoadManager().read_data(files, parent=self.ui)

    def images_loaded(self, enabled=True):
        self.ui.action_transform_detectors.setEnabled(enabled)
        self.update_color_map_bounds()
        self.update_hedm_enable_states()
        self.color_map_editor.reset_range()
        self.image_mode_widget.reset_masking()

    def open_aps_imageseries(self):
        # Get the most recent images dir
        images_dir = HexrdConfig().images_dir
        detector_names = HexrdConfig().detector_names
        selected_dirs = []
        for name in detector_names:
            caption = 'Select directory for detector: ' + name
            d = QFileDialog.getExistingDirectory(self.ui, caption,
                                                 dir=images_dir)
            if not d:
                return

            selected_dirs.append(d)
            images_dir = os.path.dirname(d)

        ImageFileManager().load_aps_imageseries(detector_names, selected_dirs)
        self.update_all()
        self.new_images_loaded.emit()

    def on_action_open_materials_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Materials File', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            HexrdConfig().load_materials(selected_file)

    def on_action_save_imageseries_triggered(self):
        if not HexrdConfig().has_images():
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
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Current View', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5);; NPZ files (*.npz)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            return self.ui.image_tab_widget.export_current_plot(selected_file)

    def on_action_run_calibration_triggered(self):
        if not hasattr(self, '_calibration_runner_async_runner'):
            # Initialize this only once and keep it around, so we don't
            # run into issues connecting/disconnecting the messages.
            self._calibration_runner_async_runner = AsyncRunner(self.ui)

        async_runner = self._calibration_runner_async_runner
        canvas = self.ui.image_tab_widget.image_canvases[0]
        runner = CalibrationRunner(canvas, async_runner)
        self._calibration_runner = runner

        try:
            runner.run()
        except Exception as e:
            QMessageBox.warning(self.ui, 'HEXRD', str(e))
            raise

    def calibration_finished(self):
        print('Calibration finished')
        print('Updating the GUI')
        self.update_config_gui()
        self.update_all()

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

        name, ok = QInputDialog.getItem(self.ui, 'HEXRD',
                                        'Select Euler Angle Convention',
                                        allowed_conventions, ind, False)

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
                create_polar_mask(name, [line])
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
        laue_overlays = [x for x in overlays if x['type'] == OverlayType.laue]
        laue_overlays = [x for x in laue_overlays if x['visible']]
        if not laue_overlays:
            msg = 'No Laue overlays found'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        data = []
        for overlay in laue_overlays:
            for det, val in overlay['data'].items():
                for ranges in val['ranges']:
                    data.append(ranges)

        if not data:
            msg = 'No Laue overlay ranges found'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        name = unique_name(HexrdConfig().raw_mask_coords, 'laue_mask')
        create_polar_mask(name, data)
        raw_data = convert_polar_to_raw(data)
        HexrdConfig().raw_mask_coords[name] = raw_data
        HexrdConfig().visible_masks.append(name)
        self.new_mask_added.emit(self.image_mode)
        HexrdConfig().polar_masks_changed.emit()

    def action_edit_apply_powder_mask_to_polar(self):
        if not HexrdConfig().show_overlays:
            msg = 'Overlays are not displayed'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        overlays = HexrdConfig().overlays
        powder_overlays = (
            [x for x in overlays if x['type'] == OverlayType.powder])
        powder_overlays = [x for x in powder_overlays if x['visible']]
        if not powder_overlays:
            msg = 'No powder overlays found'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        data = []
        for overlay in powder_overlays:
            for _, val in overlay['data'].items():
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
        create_polar_mask(name, data)
        raw_data = convert_polar_to_raw(data)
        HexrdConfig().raw_mask_coords[name] = raw_data
        HexrdConfig().visible_masks.append(name)
        self.new_mask_added.emit(self.image_mode)
        HexrdConfig().polar_masks_changed.emit()

    def on_action_edit_apply_polygon_mask_triggered(self):
        mrd = MaskRegionsDialog(self.ui)
        mrd.new_mask_added.connect(self.new_mask_added.emit)
        mrd.show()

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
            self.update_all(clear_canvases=True)

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

        has_images = HexrdConfig().has_images()

        self.ui.action_export_current_plot.setEnabled(
            (is_polar or is_cartesian) and has_images)
        self.ui.action_run_calibration.setEnabled(is_polar and has_images)
        self.ui.action_edit_apply_hand_drawn_mask.setEnabled(
            (is_polar or is_raw) and has_images)
        self.ui.action_run_wppf.setEnabled(is_polar and has_images)
        self.ui.action_edit_apply_laue_mask_to_polar.setEnabled(is_polar)
        self.ui.action_edit_apply_powder_mask_to_polar.setEnabled(is_polar)

    def start_powder_calibration(self):
        if not HexrdConfig().has_images():
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
        self.update_all()

    def update_config_gui(self):
        current_widget = self.ui.calibration_tab_widget.currentWidget()
        if current_widget is self.cal_tree_view:
            self.cal_tree_view.rebuild_tree()
        elif current_widget is self.calibration_config_widget.ui:
            self.calibration_config_widget.update_gui_from_config()
        elif current_widget is self.calibration_slider_widget.ui:
            self.calibration_slider_widget.update_gui_from_config()
        self.config_loaded.emit()

    def eventFilter(self, target, event):
        if type(target) == QMainWindow and event.type() == QEvent.Close:
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
        if not HexrdConfig().has_images():
            return

        if HexrdConfig().loading_state:
            # Skip the request if we are loading state
            return

        prev_blocked = self.calibration_config_widget.block_all_signals()

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
        else:
            rebuild_raw_masks()
            self.ui.image_tab_widget.load_images()

        self.calibration_config_widget.unblock_all_signals(prev_blocked)

    def live_update(self, enabled):
        previous = HexrdConfig().live_update
        HexrdConfig().set_live_update(enabled)

        if enabled:
            HexrdConfig().rerender_needed.connect(self.update_all)
            # Go ahead and trigger an update as well
            self.update_all()
        # Only disconnect if we were previously enabled. i.e. the signal was
        # connected
        elif previous:
            HexrdConfig().rerender_needed.disconnect(self.update_all)

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

    def new_mouse_position(self, info):
        labels = []
        labels.append(f'x = {info["x_data"]:8.3f}')
        labels.append(f'y = {info["y_data"]:8.3f}')
        delimiter = ',  '

        intensity = info['intensity']
        if intensity is not None:
            labels.append(f'value = {info["intensity"]:8.3f}')
            labels.append(f'tth = {info["tth"]:8.3f}')
            labels.append(f'eta = {info["eta"]:8.3f}')
            labels.append(f'dsp = {info["dsp"]:8.3f}')
            labels.append(f'hkl = {info["hkl"]}')

        msg = delimiter.join(labels)
        self.ui.status_bar.showMessage(msg)

    def on_action_transform_detectors_triggered(self):
        mask_state = HexrdConfig().threshold_mask_status
        self.image_mode_widget.reset_masking()
        _ = TransformDialog(self.ui).exec_()
        self.image_mode_widget.reset_masking(mask_state)

    def update_hedm_enable_states(self):
        actions = (self.ui.action_run_indexing, self.ui.action_run_fit_grains)
        for action in actions:
            action.setEnabled(False)

        image_series_dict = HexrdConfig().unagg_images
        if image_series_dict is None:
            image_series_dict = HexrdConfig().imageseries_dict

        if not image_series_dict:
            return

        # Check length of first series
        series = next(iter(image_series_dict.values()))
        if not len(series) > 1:
            return

        # If we made it here, they should be enabled.
        for action in actions:
            action.setEnabled(True)

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
            os.rename(save_file, selected_file)

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

    def on_action_load_state_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load State', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)

            # The image series will take care of closing the file
            h5_file = h5py.File(selected_file, "r")
            try:
                state.load(h5_file)
            except Exception:
                # If an exception occurred, assume we should close the file...
                h5_file.close()
                raise

    def add_view_dock_widget_actions(self):
        # Add actions to show/hide all of the dock widgets
        dock_widgets = self.ui.findChildren(QDockWidget)
        titles = [w.windowTitle() for w in dock_widgets]
        for title, w in sorted(zip(titles, dock_widgets)):
            self.ui.view_dock_widgets.addAction(w.toggleViewAction())

    def enforce_view_mode(self, raw_only):
        if raw_only:
            self.image_mode_widget.ui.tab_widget.setCurrentIndex(0)

    def apply_lorentz_polarization_correction_toggled(self, b):
        if not b:
            # Just turn it off and return
            HexrdConfig().apply_lorentz_polarization_correction = b
            return

        # Get the user to first select the Lorentz polarization options
        d = LorentzPolarizationOptionsDialog(self.ui)
        if not d.exec_():
            # Canceled... uncheck the action.
            action = self.ui.action_apply_lorentz_polarization_correction
            action.setChecked(False)
            return

        # The dialog should have modified HexrdConfig's Lorentz options
        # already. Just apply it now.
        HexrdConfig().apply_lorentz_polarization_correction = b

    def on_action_hedm_import_tool_triggered(self):
        self.load_widget.show()

    def on_action_llnl_import_tool_triggered(self):
        self.import_data_widget.show()

    def on_action_image_stack_triggered(self):
        data = ImageStackDialog(self.parent(), self.load_widget).exec_()
        if data:
            self.load_widget.image_stack_loaded(data)
            self.load_widget.show()
