from PySide2.QtCore import Signal, QObject, QSignalBlocker
from PySide2.QtWidgets import QFileDialog, QMessageBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class OmeMapsSelectDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('ome_maps_select_dialog.ui', parent)
        self.ui.setWindowTitle('Load/Generate Eta Omega Maps')

        # Hide the tab bar. It gets selected by changes to the combo box.
        self.ui.tab_widget.tabBar().hide()
        self.setup_combo_box_data()

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.select_file_button.pressed.connect(self.select_file)
        self.ui.method.currentIndexChanged.connect(self.update_method_tab)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def setup_combo_box_data(self):
        item_data = [
            'load',
            'generate'
        ]
        for i, data in enumerate(item_data):
            self.ui.method.setItemData(i, data)

    def show(self):
        self.ui.show()

    def on_accepted(self):
        # Validate
        if self.method_name == 'load' and self.file_name == '':
            msg = 'Please select a file'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            self.show()
            return

        # Save the selected options on the config
        self.update_config()

        self.accepted.emit()

    def on_rejected(self):
        self.rejected.emit()

    def select_file(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Eta Omega Maps', HexrdConfig().working_dir,
            'NPZ files (*.npz)')

        if selected_file:
            self.ui.file_name.setText(selected_file)

    @property
    def file_name(self):
        return self.ui.file_name.text()

    @property
    def threshold(self):
        return self.ui.threshold.value()

    @property
    def bin_frames(self):
        return self.ui.bin_frames.value()

    @property
    def widgets(self):
        return [
            self.ui.file_name,
            self.ui.threshold,
            self.ui.bin_frames
        ]

    def update_config(self):
        # Set the new config options on the internal config
        indexing_config = HexrdConfig().indexing_config
        maps_config = indexing_config['find_orientations']['orientation_maps']
        maps_config['file'] = self.file_name
        maps_config['threshold'] = self.threshold
        maps_config['bin_frames'] = self.bin_frames

    def update_gui(self):
        blockers = [QSignalBlocker(x) for x in self.widgets]  # noqa: F841

        indexing_config = HexrdConfig().indexing_config
        maps_config = indexing_config['find_orientations']['orientation_maps']

        file_name = maps_config['file'] if maps_config['file'] else ''

        self.ui.file_name.setText(file_name)
        self.ui.threshold.setValue(maps_config['threshold'])
        self.ui.bin_frames.setValue(maps_config['bin_frames'])

        self.update_method_tab()

    @property
    def method_name(self):
        return self.ui.method.currentData()

    @method_name.setter
    def method_name(self, v):
        w = self.ui.method
        for i in range(w.count()):
            if v == w.itemData(i):
                w.setCurrentIndex(i)
                return

        raise Exception(f'Unable to set method: {v}')

    def update_method_tab(self):
        # Take advantage of the naming scheme...
        method_tab = getattr(self.ui, self.method_name + '_tab')
        self.ui.tab_widget.setCurrentWidget(method_tab)
