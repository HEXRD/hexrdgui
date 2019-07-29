import os

from PySide2.QtCore import QEvent, QObject, Qt
from PySide2.QtWidgets import (
    QApplication, QFileDialog, QMainWindow, QMessageBox
)

from hexrd.ui.calibration_config_widget import CalibrationConfigWidget

from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.cal_tree_view import CalTreeView
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.load_hdf5_dialog import LoadHDF5Dialog
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui.materials_panel import MaterialsPanel
from hexrd.ui.resolution_editor import ResolutionEditor
from hexrd.ui.ui_loader import UiLoader


class MainWindow(QObject):

    def __init__(self, parent=None, image_files=None):
        super(MainWindow, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('main_window.ui', parent)

        # Let the left dock widget take up the whole left side
        self.ui.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        self.ui.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)

        self.color_map_editor = ColorMapEditor(self.ui.image_tab_widget,
                                               self.ui.central_widget)
        self.ui.color_map_dock_widgets.layout().addWidget(
            self.color_map_editor.ui)

        self.resolution_editor = ResolutionEditor(self.ui.central_widget)
        self.ui.resolution_dock_widgets.layout().addWidget(
            self.resolution_editor.ui)

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
        self.ui.action_save_materials.triggered.connect(
            self.on_action_save_materials_triggered)
        self.ui.action_show_live_updates.toggled.connect(
            self.live_update)
        self.ui.calibration_tab_widget.currentChanged.connect(
            self.update_config_gui)
        self.ui.image_view.pressed.connect(self.show_images)
        self.ui.cartesian_view.pressed.connect(self.show_cartesian)
        self.ui.polar_view.pressed.connect(self.show_polar)

        self.ui.action_open_images.triggered.connect(
            self.open_image_files)

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

    def on_action_save_config_triggered(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Configuration', HexrdConfig().working_dir,
            'YAML files (*.yml)')

        if selected_file:
            return HexrdConfig().save_instrument_config(selected_file)

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
            remember = True
            ext = os.path.splitext(selected_files[0])[1]
            if ImageFileManager().is_hdf5(ext) and HexrdConfig().hdf5_path == None:
                path_dialog = LoadHDF5Dialog(selected_files[0], self.ui)
                if path_dialog.ui.exec_():
                    group, data, remember = path_dialog.results()
                    HexrdConfig().hdf5_path = [group, data]

            dialog = LoadImagesDialog(selected_files, self.ui)

            if dialog.exec_():
                detector_names, image_files = dialog.results()
                ImageFileManager().load_images(detector_names, image_files)
                self.ui.image_tab_widget.load_images()

            # Clear the path if it shouldn't be remembered
            if not remember:
                HexrdConfig().hdf5_path = []

    def on_action_open_materials_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Materials File', HexrdConfig().working_dir,
            'HEXRD files (*.hexrd)')

        if selected_file:
            HexrdConfig().load_materials(selected_file)
            self.materials_panel.update_gui_from_config()

    def on_action_save_materials_triggered(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Materials', HexrdConfig().working_dir,
            'HEXRD files (*.hexrd)')

        if selected_file:
            return HexrdConfig().save_materials(selected_file)

    def show_images(self):
        self.ui.image_tab_widget.load_images()

    def show_cartesian(self):
        # Automatically make the cartesian resolution tab the active tab
        self.resolution_editor.ui.tab_widget.setCurrentIndex(0)
        self.ui.image_tab_widget.show_cartesian()

    def show_polar(self):
        # Automatically make the polar resolution tab the active tab
        self.resolution_editor.ui.tab_widget.setCurrentIndex(1)
        self.ui.image_tab_widget.show_polar()

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

    def update_all(self):
        prev_blocked = self.calibration_config_widget.block_all_signals()

        # Need to clear focus from current widget if enter is pressed or
        # else all clicks are emit an editingFinished signal and view is
        # constantly re-rendered
        if QApplication.focusWidget() is not None:
            QApplication.focusWidget().clearFocus()
        # Determine current canvas and update
        canvas = self.ui.image_tab_widget.image_canvases[0]
        if canvas.iviewer is not None:
            if canvas.iviewer.type == 'polar':
                canvas.show_polar()
            else:
                canvas.show_cartesian()
        else:
            self.show_images()

        self.calibration_config_widget.unblock_all_signals(prev_blocked)

    def live_update(self, enabled):
        HexrdConfig().set_live_update(enabled)

        dis_widgets = { self.calibration_config_widget.gui_data_changed,
                        self.cal_tree_view.model().tree_data_changed }
        pix_widgets = { self.resolution_editor.ui.cartesian_pixel_size,
                        self.resolution_editor.ui.polar_pixel_size_eta,
                        self.resolution_editor.ui.polar_pixel_size_tth }

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
