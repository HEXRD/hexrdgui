from PySide2.QtCore import QEvent, QObject, QSettings
from PySide2.QtWidgets import QFileDialog, QMainWindow

from hexrd.ui.calibration_config_widget import CalibrationConfigWidget

from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.cal_tree_widget import CalTreeWidget
from hexrd.ui.configuration import Configuration
from hexrd.ui.materials_panel import MaterialsPanel
from hexrd.ui.ui_loader import UiLoader

class MainWindow(QObject):

    def __init__(self, parent=None, image_files=None):
        super(MainWindow, self).__init__(parent)
        self.load_settings()

        loader = UiLoader()
        self.ui = loader.load_file('main_window.ui', parent)

        self.color_map_editor = ColorMapEditor(self.ui.image_tab_widget,
                                               self.ui.central_widget)
        self.ui.central_widget_layout.insertWidget(0, self.color_map_editor.ui)

        self.cfg = Configuration(self.initial_iconfig)

        self.add_materials_panel()

        self.calibration_config_widget = CalibrationConfigWidget(self.cfg,
                                                                 self.ui)
        self.cal_tree_widget = CalTreeWidget(self.cfg, self.ui)

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
        self.ui.calibration_tab_widget.currentChanged.connect(
            self.update_config_gui)
        self.ui.run_calibration.pressed.connect(self.run_calibration)
        self.ui.run_polar_calibration.pressed.connect(
            self.run_polar_calibration)

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
        self.materials_panel = MaterialsPanel(self.cfg, self.ui)
        self.ui.config_tool_box.insertItem(materials_panel_index,
                                           self.materials_panel.ui,
                                           'Materials')

    def save_settings(self):
        settings = QSettings()
        settings.setValue('iconfig', self.cfg.iconfig)

    def load_settings(self):
        settings = QSettings()
        self.initial_iconfig = settings.value('iconfig', None)

    def on_action_open_config_triggered(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Configuration', self.cfg.working_dir,
            'YAML files (*.yml)')

        if selected_file:
            self.cfg.load_iconfig(selected_file)
            self.cal_tree_widget.rebuild_tree()
            self.calibration_config_widget.update_gui_from_config()

    def on_action_save_config_triggered(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Configuration', self.cfg.working_dir,
            'YAML files (*.yml)')

        if selected_file:
            return self.cfg.save_iconfig(selected_file)

    def run_calibration(self):
        self.ui.image_tab_widget.show_calibration(self.cfg)

    def run_polar_calibration(self):
        self.ui.image_tab_widget.show_polar_calibration(self.cfg)

    def update_config_gui(self):
        current_widget = self.ui.calibration_tab_widget.currentWidget()
        if current_widget is self.cal_tree_widget:
            self.cal_tree_widget.rebuild_tree()
        elif current_widget is self.calibration_config_widget.ui:
            self.calibration_config_widget.update_gui_from_config()

    def eventFilter(self, target, event):
        if type(target) == QMainWindow and event.type() == QEvent.Close:
            # If the main window is closing, save the settings
            self.save_settings()

        return False

def main():
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    window = MainWindow()
    window.ui.show()

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
