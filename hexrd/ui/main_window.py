import os
from pathlib import Path

import numpy as np

from PySide2.QtCore import QEvent, QObject, Qt, QThreadPool, Signal, QTimer
from PySide2.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox,
    QVBoxLayout
)

from hexrd.ui.calibration_config_widget import CalibrationConfigWidget
from hexrd.ui.calibration_slider_widget import CalibrationSliderWidget

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.progress_dialog import ProgressDialog
from hexrd.ui.cal_tree_view import CalTreeView
from hexrd.ui.hand_drawn_mask_dialog import HandDrawnMaskDialog
from hexrd.ui.indexing.run import FitGrainsRunner, IndexingRunner
from hexrd.ui.indexing.fit_grains_results_dialog import FitGrainsResultsDialog
from hexrd.ui.calibration.calibration_runner import CalibrationRunner
from hexrd.ui.calibration.powder_calibration import run_powder_calibration
from hexrd.ui.calibration.wppf_runner import WppfRunner
from hexrd.ui.create_polar_mask import convert_raw_to_polar, create_polar_mask
from hexrd.ui.create_raw_mask import convert_polar_to_raw, create_raw_mask
from hexrd.ui.utils import create_unique_name
from hexrd.ui.constants import (
    OverlayType, ViewType, WORKFLOW_HEDM, WORKFLOW_LLNL)
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.import_data_panel import ImportDataPanel
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui.load_panel import LoadPanel
from hexrd.ui.mask_manager_dialog import MaskManagerDialog
from hexrd.ui.mask_regions_dialog import MaskRegionsDialog
from hexrd.ui.materials_panel import MaterialsPanel
from hexrd.ui.powder_calibration_dialog import PowderCalibrationDialog
from hexrd.ui.transform_dialog import TransformDialog
from hexrd.ui.indexing.indexing_tree_view_dialog import IndexingTreeViewDialog
from hexrd.ui.indexing.fit_grains_tree_view_dialog import (
    FitGrainsTreeViewDialog
)
from hexrd.ui.image_mode_widget import ImageModeWidget
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.workflow_selection_dialog import WorkflowSelectionDialog


class MainWindow(QObject):

    # Emitted when new images are loaded
    new_images_loaded = Signal()

    # Emitted when a new mask is added
    new_mask_added = Signal(str)

    def __init__(self, parent=None, image_files=None):
        super(MainWindow, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('main_window.ui', parent)
        self.workflow_widgets = {'HEDM': [], 'LLNL': []}

        self.thread_pool = QThreadPool(self)
        self.progress_dialog = ProgressDialog(self.ui)
        self.progress_dialog.setWindowTitle('Calibration Running')

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

        self.load_widget = LoadPanel(self.ui)
        self.ui.load_page.setLayout(QVBoxLayout())
        self.ui.load_page.layout().addWidget(self.load_widget.ui)
        self.load_widget.ui.setVisible(False)
        self.workflow_widgets[WORKFLOW_HEDM].append(self.load_widget.ui)

        self.import_data_widget = ImportDataPanel(self.color_map_editor,
                                                  self.ui)
        self.ui.load_page.setLayout(QVBoxLayout())
        self.ui.load_page.layout().addWidget(self.import_data_widget.ui)
        self.import_data_widget.ui.setVisible(False)
        self.workflow_widgets[WORKFLOW_LLNL].append(self.import_data_widget.ui)

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

        self.add_workflow_widgets()

        self.ui.action_show_live_updates.setChecked(HexrdConfig().live_update)
        self.live_update(HexrdConfig().live_update)

        ImageFileManager().load_dummy_images(True)

        # In order to avoid both a not very nice looking black window,
        # and a bug with the tabbed view
        # (see https://github.com/HEXRD/hexrdgui/issues/261),
        # do not draw the images before the first paint event has
        # occurred. The images will be drawn automatically after
        # the first paint event has occurred (see MainWindow.eventFilter).

        self.workflow_selection_dialog = WorkflowSelectionDialog(self.ui)

    def setup_connections(self):
        """This is to setup connections for non-gui objects"""
        self.ui.installEventFilter(self)
        self.ui.action_open_config_yaml.triggered.connect(
            self.on_action_open_config_yaml_triggered)
        self.ui.action_open_config_dir.triggered.connect(
            self.on_action_open_config_dir_triggered)
        self.ui.action_open_grain_fitting_results.triggered.connect(
            self.open_grain_fitting_results)
        self.ui.action_save_config_yaml.triggered.connect(
            self.on_action_save_config_yaml_triggered)
        self.ui.action_save_config_dir.triggered.connect(
            self.on_action_save_config_dir_triggered)
        self.ui.action_open_materials.triggered.connect(
            self.on_action_open_materials_triggered)
        self.ui.action_save_imageseries.triggered.connect(
            self.on_action_save_imageseries_triggered)
        self.ui.action_save_materials.triggered.connect(
            self.on_action_save_materials_triggered)
        self.ui.action_export_current_plot.triggered.connect(
            self.on_action_export_current_plot_triggered)
        self.ui.action_edit_euler_angle_convention.triggered.connect(
            self.on_action_edit_euler_angle_convention)
        self.ui.action_edit_apply_polar_mask.triggered.connect(
            self.on_action_edit_apply_polar_mask_triggered)
        self.ui.action_edit_apply_polar_mask.triggered.connect(
            self.ui.image_tab_widget.toggle_off_toolbar)
        self.ui.action_edit_apply_laue_mask_to_polar.triggered.connect(
            self.on_action_edit_apply_laue_mask_to_polar_triggered)
        self.ui.action_edit_apply_polygon_mask.triggered.connect(
            self.on_action_edit_apply_polygon_mask_triggered)
        self.ui.action_edit_apply_polygon_mask.triggered.connect(
            self.ui.image_tab_widget.toggle_off_toolbar)
        self.ui.action_edit_reset_instrument_config.triggered.connect(
            self.on_action_edit_reset_instrument_config)
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
        self.ui.action_run_fit_grains.triggered.connect(
            self.on_action_run_fit_grains_triggered)
        self.ui.action_run_wppf.triggered.connect(self.run_wppf)
        self.new_images_loaded.connect(self.update_color_map_bounds)
        self.new_images_loaded.connect(self.update_hedm_enable_states)
        self.new_images_loaded.connect(self.color_map_editor.reset_range)
        self.new_images_loaded.connect(self.image_mode_widget.reset_masking)
        self.ui.image_tab_widget.update_needed.connect(self.update_all)
        self.ui.image_tab_widget.new_mouse_position.connect(
            self.new_mouse_position)
        self.ui.image_tab_widget.clear_mouse_position.connect(
            self.ui.status_bar.clearMessage)
        self.load_widget.images_loaded.connect(self.images_loaded)
        self.import_data_widget.new_config_loaded.connect(
            self.update_config_gui)

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
        HexrdConfig().workflow_changed.connect(self.add_workflow_widgets)
        HexrdConfig().raw_masks_changed.connect(
            self.ui.image_tab_widget.load_images)

        ImageLoadManager().update_needed.connect(self.update_all)
        ImageLoadManager().new_images_loaded.connect(self.new_images_loaded)
        ImageLoadManager().images_transformed.connect(self.update_config_gui)
        ImageLoadManager().live_update_status.connect(self.live_update)

        self.ui.action_switch_workflow.triggered.connect(
            self.on_action_switch_workflow_triggered)

        self.new_mask_added.connect(self.mask_manager_dialog.update_masks_list)
        self.image_mode_widget.tab_changed.connect(
            self.mask_manager_dialog.image_mode_changed)

        HexrdConfig().calibration_complete.connect(self.calibration_finished)

    def set_icon(self, icon):
        self.ui.setWindowIcon(icon)

    def show(self):
        self.ui.show()

    def add_workflow_widgets(self):
        current_workflow = HexrdConfig().workflow
        for key in self.workflow_widgets.keys():
            visible = True if key == current_workflow else False
            for widget in self.workflow_widgets[key]:
                widget.setVisible(visible)

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

    def on_action_open_config_yaml_triggered(self):

        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Configuration', HexrdConfig().working_dir,
            'YAML files (*.yml)')

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)

            HexrdConfig().load_instrument_config(str(path))
            self.update_config_gui()

    def on_action_open_config_dir_triggered(self):
        dialog = QFileDialog(self.ui, 'Load Configuration',
                             HexrdConfig().working_dir,
                             'HEXRD directories (*)')
        dialog.setFileMode(QFileDialog.Directory)

        selected_files = []
        if dialog.exec_():
            selected_files = dialog.selectedFiles()

        if len(selected_files) == 0:
            return
        else:
            selected_file = selected_files[0]

        path = Path(selected_file)

        def _load():
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)

            # Opening a .hexrd directory, so point to config.yml
            path = path / 'config.yml'

            HexrdConfig().load_instrument_config(str(path))

        # Check we have the config.yml
        if not (path / 'config.yml').exists():
            msg = 'Invalid HEXRD directory, config.yml missing.'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        # We do this in a worker thread so the UI can refresh.
        worker = AsyncWorker(_load)
        worker.signals.finished.connect(self.update_config_gui)

        self.thread_pool.start(worker)

    def on_action_save_config_yaml_triggered(self):

        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Configuration', HexrdConfig().working_dir,
            'YAML files (*.yml)')

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return HexrdConfig().save_instrument_config(selected_file)

    def on_action_save_config_dir_triggered(self):
        dialog = QFileDialog(self.ui, 'Save Configuration',
                             HexrdConfig().working_dir,
                             'HEXRD directories (*)')
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setAcceptMode(QFileDialog.AcceptSave)

        # We connect up the curentChanged signal, so we can save a listing
        # before the QFileDialog creates a directory, so we can determine if
        # the directory already existed, see below.
        listing = []

        def _current_changed(p):
            nonlocal listing
            listing = [str(p) for p in Path(p).parent.iterdir()]
        dialog.currentChanged.connect(_current_changed)

        selected_files = []
        if dialog.exec():
            selected_files = dialog.selectedFiles()

        if len(selected_files) == 0:
            return
        else:
            selected_file = selected_files[0]

        # The QFileDialog will create the directory for us. However, if
        # the user didn't us a .hexrd suffix we need to add it, but only if is
        # didn't exist before. This is hack to get around the fact that we
        # can't easily stop QFileDialog from creating the directory.
        if Path(selected_file).suffix != '.hexrd':
            # if it wasn't in the listing before the QFileDialog, we can
            # be pretty confident that is was create by the QFileDialog.
            if selected_file not in listing:
                selected_file = Path(selected_file).rename(
                                    f'{selected_file}.hexrd')
            # else just added the suffix
            else:
                selected_file = Path(selected_file).with_suffix('.hexrd')

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)

            path.mkdir(parents=True, exist_ok=True)
            path = path / 'config.yml'

            return HexrdConfig().save_instrument_config(str(path))

    def open_grain_fitting_results(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Open Grain Fitting File', HexrdConfig().working_dir,
            'Grain fitting output files (*.out)')

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)

            data = np.loadtxt(selected_file)
            dialog = FitGrainsResultsDialog(data)
            dialog.show()
            self._fit_grains_results_dialog = dialog

    def on_detectors_changed(self):
        HexrdConfig().clear_overlay_data()
        HexrdConfig().current_imageseries_idx = 0
        self.load_dummy_images()
        self.ui.image_tab_widget.switch_toolbar(0)
        if self.workflow_selection_dialog == WORKFLOW_LLNL:
            # Update the load widget
            self.load_widget.config_changed()

    def load_dummy_images(self):
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
                self.images_loaded()

    def images_loaded(self):
        self.ui.action_transform_detectors.setEnabled(True)

    def open_aps_imageseries(self):
        # Get the most recent images dir
        images_dir = HexrdConfig().images_dir
        detector_names = HexrdConfig().detector_names
        selected_dirs = []
        for name in detector_names:
            caption = 'Select directory for detector: ' + name
            d = QFileDialog.getExistingDirectory(self.ui, caption, dir=images_dir)
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
            self.materials_panel.update_gui_from_config()
            self.materials_panel.update_structure_tab()

    def on_action_save_imageseries_triggered(self):
        if not HexrdConfig().has_images():
            msg = ('No ImageSeries available for saving.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        if ImageLoadManager().unaggregated_images:
            ims_dict = ImageLoadManager().unaggregated_images
        else:
            ims_dict = HexrdConfig().imageseries_dict

        if len(ims_dict) > 1:
            # Have the user choose an imageseries to save
            names = list(ims_dict.keys())
            name, ok = QInputDialog.getItem(self.ui, 'HEXRD',
                                            'Select ImageSeries', names, 0,
                                            False)
            if not ok:
                # User canceled...
                return
        else:
            name = list(ims_dict.keys())[0]

        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save ImageSeries', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5);; NPZ files (*.npz)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            if selected_filter.startswith('HDF5'):
                selected_format = 'hdf5'
            elif selected_filter.startswith('NPZ'):
                selected_format = 'frame-cache'

            kwargs = {}
            if selected_format == 'hdf5':
                # A path must be specified. Set it ourselves for now.
                kwargs['path'] = 'imageseries'
            elif selected_format == 'frame-cache':
                # Get the user to pick a threshold
                result, ok = QInputDialog.getDouble(self.ui, 'HEXRD',
                                                    'Choose Threshold',
                                                    10, 0, 1e12, 3)
                if not ok:
                    # User canceled...
                    return

                kwargs['threshold'] = result

                # This needs to be specified, but I think it just needs
                # to be the same as the file name...
                kwargs['cache_file'] = selected_file

            HexrdConfig().save_imageseries(ims_dict.get(name), name, selected_file,
                                           selected_format, **kwargs)

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
        canvas = self.ui.image_tab_widget.image_canvases[0]
        runner = CalibrationRunner(canvas)
        self._calibration_runner = runner

        try:
            runner.run()
        except Exception as e:
            QMessageBox.warning(self.ui, 'HEXRD', str(e))
            return

    def calibration_finished(self):
        print('Calibration finished')
        print('Updating the GUI')
        self.update_config_gui()
        self.update_all()

    def on_action_run_indexing_triggered(self):
        self._indexing_runner = IndexingRunner(self.ui)
        self._indexing_runner.run()

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
            return

    def update_color_map_bounds(self):
        self.color_map_editor.update_bounds(
            HexrdConfig().current_images_dict())

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

    def on_action_edit_apply_polar_mask_triggered(self):
        # Make the dialog
        canvas = self.ui.image_tab_widget.image_canvases[0]
        self._apply_polar_mask_line_picker = (
            HandDrawnMaskDialog(canvas, self.ui))
        self._apply_polar_mask_line_picker.start()
        self._apply_polar_mask_line_picker.finished.connect(
            self.run_apply_polar_mask)

    def run_apply_polar_mask(self, line_data):
        for line in line_data:
            name = create_unique_name(
                HexrdConfig().polar_masks_line_data, 'polar_mask_0')
            HexrdConfig().polar_masks_line_data[name] = line.copy()
            HexrdConfig().visible_masks.append(name)
            create_polar_mask([line.copy()], name)
        HexrdConfig().polar_masks_changed.emit()
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
        name = create_unique_name(
            HexrdConfig().polar_masks_line_data, 'laue_mask')
        create_polar_mask(data, name)
        HexrdConfig().polar_masks_line_data[name] = data
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

    def change_image_mode(self, mode):
        self.image_mode = mode
        self.update_image_mode_enable_states()

        # Clear the overlays
        HexrdConfig().clear_overlay_data()

        self.update_all()

    def update_image_mode_enable_states(self):
        # This is for enable states that depend on the image mode
        is_raw = self.image_mode == ViewType.raw
        is_cartesian = self.image_mode == ViewType.cartesian
        is_polar = self.image_mode == ViewType.polar

        has_images = HexrdConfig().has_images()

        self.ui.action_export_current_plot.setEnabled(
            (is_polar or is_cartesian) and has_images)
        self.ui.action_run_calibration.setEnabled(is_polar and has_images)
        self.ui.action_edit_apply_polar_mask.setEnabled(is_polar and has_images)
        self.ui.action_run_wppf.setEnabled(is_polar and has_images)
        self.ui.action_edit_apply_laue_mask_to_polar.setEnabled(is_polar)

    def start_powder_calibration(self):
        if not HexrdConfig().has_images():
            msg = ('No images available for calibration.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        d = PowderCalibrationDialog(self.ui)
        if not d.exec_():
            return

        HexrdConfig().emit_update_status_bar('Running powder calibration...')

        # Run the calibration in a background thread
        worker = AsyncWorker(run_powder_calibration)
        self.thread_pool.start(worker)

        # We currently don't have any progress updates, so make the
        # progress bar indeterminate.
        self.progress_dialog.setRange(0, 0)
        self.progress_dialog.setWindowTitle('Calibration Running')

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_powder_calibration)
        worker.signals.finished.connect(self.progress_dialog.accept)
        msg = 'Powder calibration finished!'
        f = lambda: HexrdConfig().emit_update_status_bar(msg)
        worker.signals.finished.connect(f)
        self.progress_dialog.exec_()

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
            # Rebuild polar masks
            HexrdConfig().polar_masks.clear()
            for name, line_data in HexrdConfig().polar_masks_line_data.items():
                if not isinstance(line_data, list):
                    line_data = [line_data]
                create_polar_mask(line_data, name)
            for name, value in HexrdConfig().raw_masks_line_data.items():
                det, data = value[0]
                line_data = convert_raw_to_polar(det, data)
                create_polar_mask(line_data, name)
            self.ui.image_tab_widget.show_polar()
        else:
            # Rebuild raw masks
            HexrdConfig().raw_masks.clear()
            for name, line_data in HexrdConfig().raw_masks_line_data.items():
                create_raw_mask(name, line_data)
            for name, data in HexrdConfig().polar_masks_line_data.items():
                if isinstance(data, list):
                    # These are Laue spots
                    continue
                else:
                    line_data = convert_polar_to_raw(data)
                    create_raw_mask(name, line_data)
            self.ui.image_tab_widget.load_images()

        # Only ask if have haven't asked before
        if HexrdConfig().workflow is None:
            self.workflow_selection_dialog.show()

        self.calibration_config_widget.unblock_all_signals(prev_blocked)

    def live_update(self, enabled):
        previous = HexrdConfig().live_update
        HexrdConfig().set_live_update(enabled)

        if enabled:
            HexrdConfig().rerender_needed.connect(self.update_all)
            # Go ahead and trigger an update as well
            self.update_all()
        # Only disconnect if we were previously enabled. i.e. the signal was connected
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
        labels.append('x = {:8.3f}'.format(info['x_data']))
        labels.append('y = {:8.3f}'.format(info['y_data']))
        delimiter = ',  '

        intensity = info['intensity']
        if intensity is not None:
            labels.append('value = {:8.3f}'.format(info['intensity']))

            if info['mode'] in [ViewType.cartesian, ViewType.polar]:
                labels.append('tth = {:8.3f}'.format(info['tth']))
                labels.append('eta = {:8.3f}'.format(info['eta']))
                labels.append('dsp = {:8.3f}'.format(info['dsp']))
                labels.append('hkl = ' + info['hkl'])

        msg = delimiter.join(labels)
        self.ui.status_bar.showMessage(msg)

    def on_action_transform_detectors_triggered(self):
        mask_state = HexrdConfig().threshold_mask_status
        self.image_mode_widget.reset_masking()
        td = TransformDialog(self.ui).exec_()
        self.image_mode_widget.reset_masking(mask_state)

    def on_action_switch_workflow_triggered(self):
        self.workflow_selection_dialog.show()

    def update_hedm_enable_states(self):
        actions = (self.ui.action_run_indexing, self.ui.action_run_fit_grains)
        for action in actions:
            action.setEnabled(False)

        image_series_dict = ImageLoadManager().unaggregated_images
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
