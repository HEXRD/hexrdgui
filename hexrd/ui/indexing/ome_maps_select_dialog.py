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

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.select_file_button.pressed.connect(self.select_file)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def show(self):
        self.ui.show()

    def on_accepted(self):
        # Validate
        if self.mode == 'load' and self.file_name == '':
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
    def mode(self):
        i = self.ui.tab_widget.currentIndex()
        if i == 0:
            return 'load'
        elif i == 1:
            return 'generate'

        raise Exception('Unknown index mode: ' + str(i))

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
