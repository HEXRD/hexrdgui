import os

from PySide2.QtCore import QEvent, QObject, Qt, QThreadPool, Signal, QTimer
from PySide2.QtGui import QIcon, QPixmap
from PySide2.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox,
    QVBoxLayout
)

import numpy as np

from hexrd.ui.calibration_config_widget import CalibrationConfigWidget
from hexrd.ui.calibration_slider_widget import CalibrationSliderWidget

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.progress_dialog import ProgressDialog
from hexrd.ui.cal_tree_view import CalTreeView
from hexrd.ui.line_picker_dialog import LinePickerDialog
from hexrd.ui.indexing.run import IndexingRunner
from hexrd.ui.calibration.powder_calibration import run_powder_calibration
from hexrd.ui.calibration.line_picked_calibration import (
    run_line_picked_calibration
)
from hexrd.ui.create_polar_mask import create_polar_mask
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.import_data_panel import ImportDataPanel
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui.load_panel import LoadPanel
from hexrd.ui.materials_panel import MaterialsPanel
from hexrd.ui.powder_calibration_dialog import PowderCalibrationDialog
from hexrd.ui.transform_dialog import TransformDialog
from hexrd.ui.image_mode_widget import ImageModeWidget
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui import resource_loader
import hexrd.ui.resources.icons


class MainWindow(QObject):

    # Emitted when new images are loaded
    new_images_loaded = Signal()

    def __init__(self, parent=None, image_files=None):
        super(MainWindow, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('main_window.ui', parent)

        # Load the icon
        self.load_icon()

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

        self.image_mode = 'raw'
        self.image_mode_widget = ImageModeWidget(self.ui.central_widget)
        self.ui.image_mode_dock_widgets.layout().addWidget(
            self.image_mode_widget.ui)

        self.add_materials_panel()

        self.load_widget = LoadPanel(self.ui)
        self.ui.load_page.setLayout(QVBoxLayout())
        self.ui.load_page.layout().addWidget(self.load_widget.ui)

        self.import_data_widget = ImportDataPanel(self.ui)
        self.ui.import_page.setLayout(QVBoxLayout())
        self.ui.import_page.layout().addWidget(self.import_data_widget.ui)

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

        self.setup_connections()

        self.update_config_gui()

        self.ui.action_show_live_updates.setChecked(HexrdConfig().live_update)
        self.live_update(HexrdConfig().live_update)

        ImageFileManager().load_dummy_images(True)

        # In order to avoid both a not very nice looking black window,
        # and a bug with the tabbed view
        # (see https://github.com/HEXRD/hexrdgui/issues/261),
        # do not draw the images before the first paint event has
        # occurred. The images will be drawn automatically after
        # the first paint event has occurred (see MainWindow.eventFilter).

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
        self.ui.action_export_polar_plot.triggered.connect(
            self.on_action_export_polar_plot_triggered)
        self.ui.action_edit_euler_angle_convention.triggered.connect(
            self.on_action_edit_euler_angle_convention)
        self.ui.action_edit_apply_polar_mask.triggered.connect(
            self.on_action_edit_apply_polar_mask_triggered)
        self.ui.action_edit_reset_instrument_config.triggered.connect(
            self.on_action_edit_reset_instrument_config)
        self.ui.action_transform_detectors.triggered.connect(
            self.on_action_transform_detectors_triggered)
        self.ui.action_show_live_updates.toggled.connect(
            self.live_update)
        self.ui.action_show_detector_borders.toggled.connect(
            HexrdConfig().set_show_detector_borders)
        self.ui.calibration_tab_widget.currentChanged.connect(
            self.update_config_gui)
        self.image_mode_widget.tab_changed.connect(self.change_image_mode)
        self.image_mode_widget.mask_applied.connect(self.update_all)
        self.ui.action_run_powder_calibration.triggered.connect(
            self.start_powder_calibration)
        self.ui.action_calibration_line_picker.triggered.connect(
            self.on_action_calibration_line_picker_triggered)
        self.ui.action_run_indexing.triggered.connect(
            self.on_action_run_indexing_triggered)
        self.new_images_loaded.connect(self.update_color_map_bounds)
        self.new_images_loaded.connect(self.color_map_editor.reset_range)
        self.new_images_loaded.connect(self.image_mode_widget.reset_masking)
        self.ui.image_tab_widget.update_needed.connect(self.update_all)
        self.ui.image_tab_widget.new_mouse_position.connect(
            self.new_mouse_position)
        self.ui.image_tab_widget.clear_mouse_position.connect(
            self.ui.status_bar.clearMessage)
        self.calibration_slider_widget.update_if_mode_matches.connect(
            self.update_if_mode_matches)
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
        HexrdConfig().deep_rerender_needed.connect(
            lambda: self.update_all(clear_canvases=True))

        ImageLoadManager().update_needed.connect(self.update_all)
        ImageLoadManager().new_images_loaded.connect(self.new_images_loaded)

    def load_icon(self):
        icon = resource_loader.load_resource(hexrd.ui.resources.icons,
                                             'hexrd.ico', binary=True)
        pixmap = QPixmap()
        pixmap.loadFromData(icon, 'ico')
        self.ui.setWindowIcon(QIcon(pixmap))

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

    def on_action_open_config_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Configuration', HexrdConfig().working_dir,
            'YAML files (*.yml)')

        if selected_file:
            HexrdConfig().load_instrument_config(selected_file)
            self.update_config_gui()

    def on_action_save_config_triggered(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Configuration', HexrdConfig().working_dir,
            'YAML files (*.yml)')

        if selected_file:
            return HexrdConfig().save_instrument_config(selected_file)

    def on_detectors_changed(self):
        HexrdConfig().current_imageseries_idx = 0
        self.load_dummy_images()
        self.ui.image_tab_widget.switch_toolbar(0)
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

            # Make sure the names and number of files and
            # names and number of detectors match
            num_detectors = len(HexrdConfig().detector_names)
            if len(selected_files) != num_detectors:
                msg = ('Number of files must match number of detectors: ' +
                       str(num_detectors))
                QMessageBox.warning(self.ui, 'HEXRD', msg)
                return

            files = ImageLoadManager().check_images(selected_files)
            if not files:
                return

            # If it is a hdf5 file allow the user to select the path
            ext = os.path.splitext(selected_files[0])[1]
            if (ImageFileManager().is_hdf5(ext) and not
                    ImageFileManager().path_exists(selected_files[0])):

                ImageFileManager().path_prompt(selected_files[0])

            dialog = LoadImagesDialog(selected_files, self.ui)

            if dialog.exec_():
                detector_names, image_files = dialog.results()
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
            'HEXRD files (*.hexrd)')

        if selected_file:
            HexrdConfig().load_materials(selected_file)
            self.materials_panel.update_gui_from_config()

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
            'HEXRD files (*.hexrd)')

        if selected_file:
            return HexrdConfig().save_materials(selected_file)

    def on_action_export_polar_plot_triggered(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Polar Image', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5);; NPZ files (*.npz)')

        if selected_file:
            return self.ui.image_tab_widget.export_polar_plot(selected_file)

    def on_action_calibration_line_picker_triggered(self):
        # Do a quick check for refinable paramters, which are required
        flags = HexrdConfig().get_statuses_instrument_format()
        if np.count_nonzero(flags) == 0:
            msg = 'There are no refinable parameters'
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        # Make the dialog
        canvas = self.ui.image_tab_widget.image_canvases[0]
        self._calibration_line_picker = LinePickerDialog(canvas, self.ui)
        self._calibration_line_picker.start()
        self._calibration_line_picker.finished.connect(
            self.start_line_picked_calibration)

    def start_line_picked_calibration(self, line_data):
        HexrdConfig().emit_update_status_bar('Running powder calibration...')

        # Run the calibration in a background thread
        worker = AsyncWorker(run_line_picked_calibration, line_data)
        self.thread_pool.start(worker)

        # We currently don't have any progress updates, so make the
        # progress bar indeterminate.
        self.progress_dialog.setRange(0, 0)

        # Get the results and close the progress dialog when finished
        worker.signals.result.connect(self.finish_line_picked_calibration)
        worker.signals.finished.connect(self.progress_dialog.accept)
        msg = 'Powder calibration finished!'
        f = lambda: HexrdConfig().emit_update_status_bar(msg)
        worker.signals.finished.connect(f)
        self.progress_dialog.exec_()

    def finish_line_picked_calibration(self, res):
        print('Received result from line picked calibration')

        if res is not True:
            print('Optimization failed!')
            return

        print('Updating the GUI')
        self.update_config_gui()
        self.update_all()

    def on_action_run_indexing_triggered(self):
        self._indexing_runner = IndexingRunner(self.ui)
        self._indexing_runner.run()

    def update_color_map_bounds(self):
        self.color_map_editor.update_bounds(
            HexrdConfig().current_images_dict())

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

        HexrdConfig().set_euler_angle_convention(chosen, extrinsic)

        self.update_all()
        self.update_config_gui()

    def on_action_edit_apply_polar_mask_triggered(self):
        # Make the dialog
        canvas = self.ui.image_tab_widget.image_canvases[0]
        self._apply_polar_mask_line_picker = LinePickerDialog(canvas, self.ui)
        self._apply_polar_mask_line_picker.start()
        self._apply_polar_mask_line_picker.finished.connect(
            self.run_apply_polar_mask)

    def run_apply_polar_mask(self, line_data):
        HexrdConfig().polar_masks_line_data.append(line_data.copy())
        self.update_all()

    def on_action_edit_reset_instrument_config(self):
        HexrdConfig().restore_instrument_config_backup()
        self.update_config_gui()

    def change_image_mode(self, text):
        self.image_mode = text.lower()
        self.update_image_mode_enable_states()
        self.update_all()

    def update_image_mode_enable_states(self):
        # This is for enable states that depend on the image mode
        is_raw = self.image_mode == 'raw'
        is_cartesian = self.image_mode == 'cartesian'
        is_polar = self.image_mode == 'polar'

        has_images = HexrdConfig().has_images()

        self.ui.action_export_polar_plot.setEnabled(is_polar and has_images)
        self.ui.action_calibration_line_picker.setEnabled(
            is_polar and has_images)
        self.ui.action_edit_apply_polar_mask.setEnabled(is_polar and has_images)

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
            # Rebuild polar masks
            del HexrdConfig().polar_masks[:]
            for line_data in HexrdConfig().polar_masks_line_data:
                create_polar_mask(line_data)
            self.ui.image_tab_widget.show_polar()
        else:
            self.ui.image_tab_widget.load_images()

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

    def new_mouse_position(self, info):
        labels = []
        labels.append('x = {:8.3f}'.format(info['x_data']))
        labels.append('y = {:8.3f}'.format(info['y_data']))
        delimiter = ',  '

        intensity = info['intensity']
        if intensity is not None:
            labels.append('value = {:8.3f}'.format(info['intensity']))

            if info['mode'] in ['cartesian', 'polar']:
                labels.append('tth = {:8.3f}'.format(info['tth']))
                labels.append('eta = {:8.3f}'.format(info['eta']))
                labels.append('dsp = {:8.3f}'.format(info['dsp']))
                labels.append('hkl = ' + info['hkl'])

        msg = delimiter.join(labels)
        self.ui.status_bar.showMessage(msg)

    def on_action_transform_detectors_triggered(self):
        mask_state = HexrdConfig().threshold_mask
        self.image_mode_widget.reset_masking()
        td = TransformDialog(self.ui).exec_()
        self.image_mode_widget.reset_masking(mask_state)
