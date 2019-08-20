import os

from PySide2.QtCore import QEvent, QObject, Qt, QThreadPool, Signal
from PySide2.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox
)

from hexrd.ui.calibration_config_widget import CalibrationConfigWidget

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.cal_progress_dialog import CalProgressDialog
from hexrd.ui.cal_tree_view import CalTreeView
from hexrd.ui.calibration_crystal_editor import CalibrationCrystalEditor
from hexrd.ui.calibration.powder_calibration import run_powder_calibration
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui.materials_panel import MaterialsPanel
from hexrd.ui.powder_calibration_dialog import PowderCalibrationDialog
from hexrd.ui.image_mode_widget import ImageModeWidget
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.process_ims_dialog import ProcessIMSDialog
from hexrd.ui.frame_aggregation import FrameAggregation
from hexrd.ui.wedge_editor import WedgeEditor


class MainWindow(QObject):

    # Emitted when new images are loaded
    new_images_loaded = Signal()

    def __init__(self, parent=None, image_files=None):
        super(MainWindow, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('main_window.ui', parent)

        self.thread_pool = QThreadPool(self)
        self.cal_progress_dialog = CalProgressDialog(self.ui)

        # Let the left dock widget take up the whole left side
        self.ui.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        self.ui.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)

        self.color_map_editor = ColorMapEditor(self.ui.image_tab_widget,
                                               self.ui.central_widget)
        self.ui.color_map_dock_widgets.layout().addWidget(
            self.color_map_editor.ui)

        self.image_mode = 'raw'
        self.image_mode_widget = ImageModeWidget(self.ui.central_widget)
        self.ui.image_mode_dock_widgets.layout().addWidget(
            self.image_mode_widget.ui)

        self.frame_aggregation = FrameAggregation(self.ui.central_widget)
        self.ui.frame_aggregation_widgets.layout().addWidget(
            self.frame_aggregation.ui)

        self.add_materials_panel()

        self.calibration_config_widget = CalibrationConfigWidget(self.ui)
        self.cal_tree_view = CalTreeView(self.ui)

        tab_texts = ['Tree View', 'Form View']
        self.ui.calibration_tab_widget.clear()
        self.ui.calibration_tab_widget.addTab(self.cal_tree_view,
                                              tab_texts[0])
        self.ui.calibration_tab_widget.addTab(
            self.calibration_config_widget.ui, tab_texts[1])

        self.setup_connections()

        self.calibration_config_widget.update_gui_from_config()

        self.ui.action_show_live_updates.setChecked(HexrdConfig().live_update)

    def setup_connections(self):
        """This is to setup connections for non-gui objects"""
        self.ui.installEventFilter(self)
        self.ui.action_open_config.triggered.connect(
            self.on_action_open_config_triggered)
        self.ui.action_save_config.triggered.connect(
            self.on_action_save_config_triggered)
        self.ui.action_open_materials.triggered.connect(
            self.on_action_open_materials_triggered)
        self.ui.action_save_imageseries.triggered.connect(
            self.on_action_save_imageseries_triggered)
        self.ui.action_save_materials.triggered.connect(
            self.on_action_save_materials_triggered)
        self.ui.action_edit_ims.triggered.connect(
            self.on_action_edit_ims)
        self.ui.action_edit_angles.triggered.connect(
            self.on_action_edit_angles)
        self.ui.action_edit_euler_angle_convention.triggered.connect(
            self.on_action_edit_euler_angle_convention)
        self.ui.action_edit_calibration_crystal.triggered.connect(
            self.on_action_edit_calibration_crystal)
        self.ui.action_show_live_updates.toggled.connect(
            self.live_update)
        self.ui.calibration_tab_widget.currentChanged.connect(
            self.update_config_gui)
        self.image_mode_widget.tab_changed.connect(self.change_image_mode)
        self.ui.action_run_powder_calibration.triggered.connect(
            self.start_powder_calibration)
        self.new_images_loaded.connect(self.enable_editing_ims)
        self.new_images_loaded.connect(self.color_map_editor.update_bounds)
        self.ui.image_tab_widget.update_needed.connect(self.update_all)
        self.ui.image_tab_widget.new_mouse_position.connect(
            self.new_mouse_position)
        self.ui.image_tab_widget.clear_mouse_position.connect(
            self.ui.status_bar.clearMessage)

        self.ui.action_open_images.triggered.connect(
            self.open_image_files)
        self.ui.action_open_aps_imageseries.triggered.connect(
            self.open_aps_imageseries)
        HexrdConfig().update_status_bar.connect(
            self.ui.status_bar.showMessage)

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

    def on_action_open_config_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Configuration', HexrdConfig().working_dir,
            'YAML files (*.yml)')

        if selected_file:
            HexrdConfig().load_instrument_config(selected_file)
            self.cal_tree_view.rebuild_tree()
            self.calibration_config_widget.update_gui_from_config()
            self.update_all(clear_canvases=True)

    def on_action_save_config_triggered(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Configuration', HexrdConfig().working_dir,
            'YAML files (*.yml)')

        if selected_file:
            return HexrdConfig().save_instrument_config(selected_file)

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

            # Make sure the number of files and number of detectors match
            num_detectors = len(HexrdConfig().get_detector_names())
            if len(selected_files) != num_detectors:
                msg = ('Number of files must match number of detectors: ' +
                       str(num_detectors))
                QMessageBox.warning(self.ui, 'HEXRD', msg)
                return

            # If it is a hdf5 file allow the user to select the path
            ext = os.path.splitext(selected_files[0])[1]
            if (ImageFileManager().is_hdf5(ext) and not
                    ImageFileManager().path_exists(selected_files[0])):

                ImageFileManager().path_prompt(selected_files[0])

            dialog = LoadImagesDialog(selected_files, self.ui)

            if dialog.exec_():
                detector_names, image_files = dialog.results()
                ImageFileManager().load_images(detector_names, image_files)
                self.ui.action_edit_ims.setEnabled(True)
                self.ui.action_edit_angles.setEnabled(True)
                self.update_all()
                self.new_images_loaded.emit()

    def open_aps_imageseries(self):
        # Get the most recent images dir
        images_dir = HexrdConfig().images_dir
        detector_names = HexrdConfig().get_detector_names()
        selected_dirs = []
        for name in detector_names:
            caption = 'Select directory for detector: ' + name
            d = QFileDialog.getExistingDirectory(self.ui, caption, dir=images_dir)
            if not d:
                return

            selected_dirs.append(d)
            images_dir = os.path.dirname(d)

        ImageFileManager().load_aps_imageseries(detector_names, selected_dirs)
        self.ui.action_edit_ims.setEnabled(True)
        self.ui.action_edit_angles.setEnabled(True)
        self.update_all()
        self.new_images_loaded.emit()

    def on_action_open_materials_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Materials File', HexrdConfig().working_dir,
            'HEXRD files (*.hexrd)')

        if selected_file:
            HexrdConfig().load_materials(selected_file)
            self.materials_panel.update_gui_from_config()

    def on_action_save_imageseries_triggered(self):
        if not HexrdConfig().has_images():
            msg = ('No ImageSeries available for saving.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        if len(HexrdConfig().imageseries_dict) > 1:
            # Have the user choose an imageseries to save
            names = list(HexrdConfig().imageseries_dict.keys())
            name, ok = QInputDialog.getItem(self.ui, 'HEXRD',
                                            'Select ImageSeries', names, 0,
                                            False)
            if not ok:
                # User canceled...
                return
        else:
            name = list(HexrdConfig().imageseries_dict.keys())[0]

        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save ImageSeries', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5);; NPZ files (*.npz)')

        if selected_file:
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

            HexrdConfig().save_imageseries(name, selected_file,
                                           selected_format, **kwargs)

    def on_action_save_materials_triggered(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Materials', HexrdConfig().working_dir,
            'HEXRD files (*.hexrd)')

        if selected_file:
            return HexrdConfig().save_materials(selected_file)

    def enable_editing_ims(self):
        self.ui.action_edit_ims.setEnabled(HexrdConfig().has_images())

    def on_action_edit_ims(self):
        # open dialog
        ProcessIMSDialog(self)

    def on_action_edit_angles(self):
        WedgeEditor(self.ui)

    def on_action_edit_euler_angle_convention(self):
        allowed_conventions = [
            'None',
            'Extrinsic XYZ',
            'Intrinsic ZXZ'
        ]
        current = HexrdConfig().euler_angle_convention
        ind = 0
        if current[0] is not None and current[1] is not None:
            for i, convention in enumerate(allowed_conventions):
                is_extr = 'Extrinsic' in convention
                if current[0].upper() in convention and current[1] == is_extr:
                    ind = i
                    break

        name, ok = QInputDialog.getItem(self.ui, 'HEXRD',
                                        'Select Euler Angle Convention',
                                        allowed_conventions, ind, False)

        if not ok:
            # User canceled...
            return

        if name == 'None':
            chosen = None
            extrinsic = None
        else:
            chosen = name.split()[1].lower()
            extrinsic = 'Extrinsic' in name

        msg = 'Update current tilt angles?'
        if QMessageBox.question(self.ui, 'HEXRD', msg):
            HexrdConfig().set_euler_angle_convention(chosen, extrinsic)
        else:
            HexrdConfig()._euler_angle_convention = (chosen, extrinsic)

        self.update_config_gui()

    def on_action_edit_calibration_crystal(self):
        if not hasattr(self, 'calibration_crystal_editor'):
            self.calibration_crystal_editor = CalibrationCrystalEditor(self.ui)
        else:
            # Update the GUI in case it needs updating
            self.calibration_crystal_editor.update_gui_from_config()

        self.calibration_crystal_editor.exec_()

    def change_image_mode(self, text):
        self.image_mode = text.lower()
        self.update_all()

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

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_powder_calibration)
        worker.signals.finished.connect(self.cal_progress_dialog.accept)
        msg = 'Powder calibration finished!'
        f = lambda: HexrdConfig().emit_update_status_bar(msg)
        worker.signals.finished.connect(f)
        self.cal_progress_dialog.exec_()

    def finish_powder_calibration(self):
        self.update_config_gui()
        self.update_all()

    def update_config_gui(self):
        current_widget = self.ui.calibration_tab_widget.currentWidget()
        if current_widget is self.cal_tree_view:
            self.cal_tree_view.rebuild_tree()
        elif current_widget is self.calibration_config_widget.ui:
            self.calibration_config_widget.update_gui_from_config()

    def eventFilter(self, target, event):
        if type(target) == QMainWindow and event.type() == QEvent.Close:
            # If the main window is closing, save the config settings
            HexrdConfig().save_settings()

        return False

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

        if self.image_mode == 'cartesian':
            self.ui.image_tab_widget.show_cartesian()
        elif self.image_mode == 'polar':
            self.ui.image_tab_widget.show_polar()
        else:
            self.ui.image_tab_widget.load_images()

        self.calibration_config_widget.unblock_all_signals(prev_blocked)

    def live_update(self, enabled):
        HexrdConfig().set_live_update(enabled)

        dis_widgets = {self.calibration_config_widget.gui_data_changed,
                       self.cal_tree_view.model().tree_data_changed}
        pix_widgets = {self.image_mode_widget.ui.cartesian_pixel_size,
                       self.image_mode_widget.ui.polar_pixel_size_eta,
                       self.image_mode_widget.ui.polar_pixel_size_tth}

        for widget in dis_widgets:
            if enabled:
                widget.connect(self.update_all)
            else:
                widget.disconnect(self.update_all)
        self.calibration_config_widget.set_keyboard_tracking(not enabled)

        for widget in pix_widgets:
            if enabled:
                widget.editingFinished.connect(self.update_all)
            else:
                widget.editingFinished.disconnect(self.update_all)
            widget.setKeyboardTracking(not enabled)

    def new_mouse_position(self, x, y, x_data, y_data, intensity):
        x_str = 'x = {:8.3f}'.format(x_data)
        y_str = 'y = {:8.3f}'.format(y_data)
        between = ',  '
        msg = x_str + between + y_str

        if intensity != 0.0:
            # The intensity will be exactly 0.0 if "None" was passed
            intensity = 'value = {:8.3f}'.format(intensity)
            msg += between + intensity

        self.ui.status_bar.showMessage(msg)
