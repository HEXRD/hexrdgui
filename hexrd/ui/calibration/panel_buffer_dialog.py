import os

from PySide2.QtCore import Signal, QObject, QSignalBlocker
from PySide2.QtWidgets import QFileDialog, QMessageBox
import numpy as np

from hexrd.ui import enter_key_filter

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader

CONFIG_MODE_BORDER = 'border'
CONFIG_MODE_NUMPY = 'numpy'


class PanelBufferDialog(QObject):

    accepted = Signal()
    rejected = Signal()
    finished = Signal(int)

    def __init__(self, detector, parent=None):
        super().__init__(parent)

        self.detector = detector
        loader = UiLoader()
        self.ui = loader.load_file('panel_buffer_dialog.ui')
        self.ui.installEventFilter(enter_key_filter)

        # Hide the tab bar. It gets selected by changes to the combo box.
        self.ui.tab_widget.tabBar().hide()
        self.setup_combo_box_data()

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.select_file_button.pressed.connect(self.select_file)
        self.ui.config_mode.currentIndexChanged.connect(self.update_mode_tab)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def setup_combo_box_data(self):
        item_data = [
            CONFIG_MODE_BORDER,
            CONFIG_MODE_NUMPY
        ]
        for i, data in enumerate(item_data):
            self.ui.config_mode.setItemData(i, data)

    def show(self):
        self.ui.show()

    def on_accepted(self):
        if self.mode == CONFIG_MODE_NUMPY and self.file_name == '':
            msg = 'Please select a NumPy array file'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            self.show()
            return

        if self.update_config():
            self.accepted.emit()
            self.finished.emit(self.ui.result())

    def on_rejected(self):
        self.rejected.emit()
        self.finished.emit(self.ui.result())

    def select_file(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Panel Buffer', HexrdConfig().working_dir,
            'NPY files (*.npy)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            self.ui.file_name.setText(selected_file)

    @property
    def file_name(self):
        return self.ui.file_name.text()

    @property
    def x_border(self):
        return self.ui.border_x_spinbox.value()

    @property
    def y_border(self):
        return self.ui.border_y_spinbox.value()

    @property
    def widgets(self):
        return [
            self.ui.file_name,
            self.ui.border_x_spinbox,
            self.ui.border_y_spinbox
        ]

    def update_config(self):
        # Set the new config options on the internal config
        config = HexrdConfig().config
        detector_config = config['instrument']['detectors'][self.detector]

        buffer_default = {'status': 0}
        buffer = detector_config.setdefault('buffer', buffer_default)
        if self.mode == CONFIG_MODE_BORDER:
            buffer['value'] = [self.x_border, self.y_border]
        else:
            array = np.load(self.file_name)

            # Must match the detector size
            detector_shape = (detector_config['pixels']['rows']['value'],
                              detector_config['pixels']['columns']['value'])

            if array.shape != detector_shape:
                msg = 'The NumPy array shape must match the detector'
                QMessageBox.critical(self.ui, 'HEXRD', msg)
                self.show()
                return False

            buffer['value'] = array

        return True

    def update_gui(self):
        blockers = [QSignalBlocker(x) for x in self.widgets]  # noqa: F841

        config = HexrdConfig().config
        detector_config = config['instrument']['detectors'][self.detector]

        if 'buffer' in detector_config:
            buffer = detector_config['buffer']['value']

            if isinstance(buffer, np.ndarray):
                self.mode = CONFIG_MODE_NUMPY
            elif isinstance(buffer, list):
                self.mode = CONFIG_MODE_BORDER
                if np.isscalar(buffer):
                    buffer = [buffer]*2

                self.ui.border_x_spinbox.setValue(buffer[0])
                self.ui.border_y_spinbox.setValue(buffer[1])

        self.update_mode_tab()

    @property
    def mode(self):
        return self.ui.config_mode.currentData()

    @mode.setter
    def mode(self, v):
        w = self.ui.config_mode
        for i in range(w.count()):
            if v == w.itemData(i):
                w.setCurrentIndex(i)
                return

        raise Exception(f'Unable to set config mode: {v}')

    def update_mode_tab(self):
        mode_tab = getattr(self.ui, self.mode + '_tab')
        self.ui.tab_widget.setCurrentWidget(mode_tab)
