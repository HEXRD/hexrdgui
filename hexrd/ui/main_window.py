import os

from PySide2.QtCore import QEvent, QObject, Qt
from PySide2.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from hexrd.ui.calibration_config_widget import CalibrationConfigWidget

from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.cal_tree_widget import CalTreeWidget
from hexrd.ui.hexrd_config import HexrdConfig
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
        self.cal_tree_widget = CalTreeWidget(self.ui)

        tab_texts = ['Tree View', 'Form View']
        self.ui.calibration_tab_widget.clear()
        self.ui.calibration_tab_widget.addTab(self.cal_tree_widget,
                                              tab_texts[0])
        self.ui.calibration_tab_widget.addTab(
            self.calibration_config_widget.ui, tab_texts[1])

        self.setup_connections()

        self.calibration_config_widget.update_gui_from_config()

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
        self.ui.calibration_tab_widget.currentChanged.connect(
            self.update_config_gui)
        self.ui.run_calibration.pressed.connect(self.run_calibration)
        self.ui.run_polar_calibration.pressed.connect(
            self.run_polar_calibration)

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
            self.cal_tree_widget.rebuild_tree()
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

            dialog = LoadImagesDialog(selected_files, self.ui)

            if dialog.exec_():
                detector_names, image_files = dialog.results()
                HexrdConfig().load_images(detector_names, image_files)
                self.ui.image_tab_widget.load_images()

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

    def run_calibration(self):
        # Automatically make the cartesian resolution tab the active tab
        self.resolution_editor.ui.tab_widget.setCurrentIndex(0)
        self.ui.image_tab_widget.show_calibration()

    def run_polar_calibration(self):
        # Automatically make the polar resolution tab the active tab
        self.resolution_editor.ui.tab_widget.setCurrentIndex(1)
        self.ui.image_tab_widget.show_polar_calibration()

    def update_config_gui(self):
        current_widget = self.ui.calibration_tab_widget.currentWidget()
        if current_widget is self.cal_tree_widget:
            self.cal_tree_widget.rebuild_tree()
        elif current_widget is self.calibration_config_widget.ui:
            self.calibration_config_widget.update_gui_from_config()

    def eventFilter(self, target, event):
        if type(target) == QMainWindow and event.type() == QEvent.Close:
            # If the main window is closing, save the config settings
            HexrdConfig().save_settings()

        return False


def main():
    import signal
    import sys
    from PySide2.QtWidgets import QApplication

    # Kill the program when ctrl-c is used
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)

    window = MainWindow()
    window.ui.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
