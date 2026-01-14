import copy
import os

from PySide6.QtCore import Signal, QObject, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

import matplotlib.pyplot as plt
import numpy as np

from hexrd.utils.panel_buffer import (
    panel_buffer_from_str,
    valid_panel_buffer_names,
)

from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals
from hexrdgui.utils.dialog import add_help_url

CONFIG_MODE_BORDER = 'border'
CONFIG_MODE_NUMPY = 'numpy'
CONFIG_MODE_NAME = 'name'


class PanelBufferDialog(QObject):

    accepted = Signal()
    rejected = Signal()
    finished = Signal(int)

    def __init__(self, detector, parent=None):
        super().__init__(parent)

        self.detector = detector
        loader = UiLoader()
        self.ui = loader.load_file('panel_buffer_dialog.ui')

        self.ui.setWindowTitle(f'Configure panel buffer for {detector}')

        # Keep the dialog in front
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        add_help_url(self.ui.button_box, 'configuration/instrument/#panel-buffer')

        # Hide the tab bar. It gets selected by changes to the combo box.
        self.ui.tab_widget.tabBar().hide()
        self.setup_combo_box_data()
        self.setup_valid_names()

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
            CONFIG_MODE_NUMPY,
            CONFIG_MODE_NAME,
        ]
        for i, data in enumerate(item_data):
            self.ui.config_mode.setItemData(i, data)

    def setup_valid_names(self):
        w = self.ui.selected_name
        w.clear()
        w.addItems(valid_panel_buffer_names())

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
            HexrdConfig().rerender_needed.emit()
            self.finished.emit(self.ui.result())

    def on_rejected(self):
        self.rejected.emit()
        self.finished.emit(self.ui.result())

    def select_file(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Panel Buffer', HexrdConfig().working_dir, 'NPY files (*.npy)'
        )

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
            self.ui.border_y_spinbox,
            self.ui.selected_name,
        ]

    @property
    def current_editing_buffer_value(self):
        if self.mode == CONFIG_MODE_BORDER:
            return [self.x_border, self.y_border]
        elif self.mode == CONFIG_MODE_NAME:
            return self.ui.selected_name.currentText()
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
        return self.detector_config.get('buffer', self.default_buffer)

    @property
    def detector_config(self):
        return HexrdConfig().detector(self.detector)

    @property
    def detector_shape(self):
        pixels = self.detector_config['pixels']
        return (pixels['rows'], pixels['columns'])

    def update_config(self):
        # Set the new config options on the internal config
        value = self.current_editing_buffer_value
        if value is None:
            return False

        self.detector_config['buffer'] = value

        if isinstance(value, str):
            # Check if this has ROIs and a group
            # If so, ask if the user wants to apply this setting
            # to all detectors in this group.
            group = HexrdConfig().detector_group(self.detector)
            if HexrdConfig().instrument_has_roi and group:
                det_keys = HexrdConfig().detectors_in_group(group)
                if len(det_keys) > 1:
                    title = 'Apply to Other Detectors?'
                    msg = (
                        f'Set panel buffer "{value}" to all '
                        f'detectors in the group "{group}"?'
                    )
                    response = QMessageBox.question(self.ui, title, msg)
                    if response == QMessageBox.Yes:
                        for det_key in det_keys:
                            config = HexrdConfig().detector(det_key)
                            config['buffer'] = value

        return True

    def update_gui(self):
        with block_signals(*self.widgets):
            if 'buffer' in self.detector_config:
                buffer = self.detector_config['buffer']
                if isinstance(buffer, str):
                    self.mode = CONFIG_MODE_NAME
                    self.ui.selected_name.setCurrentText(buffer)
                else:
                    buffer = np.asarray(buffer)

                    if buffer.size in (1, 2):
                        self.mode = CONFIG_MODE_BORDER
                        if np.array_equal(buffer, None):
                            buffer = np.asarray([0])

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
        has_numpy_array = False
        if not isinstance(self.current_editing_buffer_value, str):
            buffer = np.asarray(self.current_editing_buffer_value)
            has_numpy_array = buffer.size > 2

        self.ui.show_panel_buffer.setEnabled(has_numpy_array)

    def clear_panel_buffer(self):
        # Clear the config options on the internal config
        self.detector_config['buffer'] = self.default_buffer
        self.update_enable_states()
        HexrdConfig().rerender_needed.emit()

    @property
    def default_buffer(self):
        return [0.0, 0.0]

    def show_panel_buffer(self):
        buffer = self.current_editing_buffer_value
        if isinstance(buffer, str):
            instr = create_hedm_instrument()
            panel = instr.detectors[self.detector]
            buffer = panel_buffer_from_str(buffer, panel)
        else:
            buffer = np.asarray(buffer)
            if buffer.size <= 2:
                # We only support showing numpy array buffers currently
                return

        fig, ax = plt.subplots()
        fig.canvas.manager.set_window_title(f'{self.detector}')
        ax.set_title('Panel Buffer')

        ax.imshow(buffer, vmin=0, vmax=1)
        fig.canvas.draw_idle()
        fig.show()
