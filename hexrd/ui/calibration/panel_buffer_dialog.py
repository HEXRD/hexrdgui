import copy
import os

from PySide2.QtCore import Signal, QObject
from PySide2.QtWidgets import QFileDialog, QMessageBox

import matplotlib.pyplot as plt
import numpy as np

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals
from hexrd.ui.utils.dialog import add_help_url

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

        add_help_url(self.ui.button_box,
                     'configuration/instrument/#panel-buffer')

        # Hide the tab bar. It gets selected by changes to the combo box.
        self.ui.tab_widget.tabBar().hide()
        self.setup_combo_box_data()

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.config_mode.currentIndexChanged.connect(self.update_mode_tab)
        self.ui.file_name.editingFinished.connect(self.update_enable_states)
        self.ui.select_file_button.clicked.connect(self.select_file)
        self.ui.show_panel_buffer.clicked.connect(self.show_panel_buffer)
        self.ui.clear_panel_buffer.clicked.connect(self.clear_panel_buffer)
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
            print(msg)
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
            self.file_name = selected_file

    @property
    def file_name(self):
        return self.ui.file_name.text()

    @file_name.setter
    def file_name(self, v):
        self.ui.file_name.setText(v)
        self.update_enable_states()

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

    @property
    def current_editing_buffer_value(self):
        if self.mode == CONFIG_MODE_BORDER:
            return [self.x_border, self.y_border]
        elif self.file_name == '':
            # Just return the currently saved buffer
            return copy.deepcopy(self.current_saved_buffer_value)

        try:
            array = np.load(self.file_name)
        except FileNotFoundError:
            msg = f'"{self.file_name}" does not exist'
            print(msg)
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            self.show()
            return None

        # Must match the detector size
        if array.shape != self.detector_shape:
            msg = 'The NumPy array shape must match the detector'
            print(msg)
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            self.show()
            return None

        return array

    @property
    def current_saved_buffer_value(self):
        return self.detector_config.get('buffer', self.default_buffer)['value']

    @property
    def detector_config(self):
        return HexrdConfig().detector(self.detector)

    @property
    def detector_shape(self):
        pixels = self.detector_config['pixels']
        return (pixels['rows']['value'], pixels['columns']['value'])

    def update_config(self):
        # Set the new config options on the internal config
        value = self.current_editing_buffer_value
        if value is None:
            return False

        buffer = self.detector_config.setdefault('buffer', self.default_buffer)
        buffer['value'] = value

        return True

    def update_gui(self):
        with block_signals(*self.widgets):
            if 'buffer' in self.detector_config:
                buffer = np.asarray(self.detector_config['buffer']['value'])

                if buffer.size in (1, 2):
                    self.mode = CONFIG_MODE_BORDER
                    if buffer.size == 1:
                        buffer = [buffer.item()] * 2

                    self.ui.border_x_spinbox.setValue(buffer[0])
                    self.ui.border_y_spinbox.setValue(buffer[1])
                else:
                    self.mode = CONFIG_MODE_NUMPY

            self.update_mode_tab()

        self.update_enable_states()

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
        self.update_enable_states()

    def update_enable_states(self):
        buffer = np.asarray(self.current_editing_buffer_value)
        has_numpy_array = buffer.size > 2
        self.ui.show_panel_buffer.setEnabled(has_numpy_array)

    def clear_panel_buffer(self):
        # Clear the config options on the internal config
        self.detector_config['buffer'] = self.default_buffer
        self.update_enable_states()

    @property
    def default_buffer(self):
        return {
            'status': 0,
            'value': [0., 0.],
        }

    def show_panel_buffer(self):
        buffer = np.asarray(self.current_editing_buffer_value)
        if buffer.size <= 2:
            # We only support showing numpy array buffers currently
            return

        fig, ax = plt.subplots()
        fig.canvas.manager.set_window_title(f'{self.detector}')
        ax.set_title('Panel Buffer')

        ax.imshow(buffer)
        fig.canvas.draw_idle()
        fig.show()
