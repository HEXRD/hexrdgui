from __future__ import annotations

import copy
import os
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hexrd.instrument import Detector

from PySide6.QtCore import Signal, QObject, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

import matplotlib.pyplot as plt
import numpy as np

from hexrd.utils.panel_buffer import (
    panel_buffer_as_2d_array,
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

    def __init__(self, detector: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.detector = detector
        loader = UiLoader()
        self.ui = loader.load_file('panel_buffer_dialog.ui')

        self.ui.setWindowTitle(f'Configure panel buffer for {detector}')

        # Keep the dialog in front
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.WindowType.Tool)

        add_help_url(self.ui.button_box, 'configuration/instrument/#panel-buffer')

        # Hide the tab bar. It gets selected by changes to the combo box.
        self.ui.tab_widget.tabBar().hide()
        self.setup_combo_box_data()
        self.setup_valid_names()

        self.update_gui()

        self.setup_connections()

    def setup_connections(self) -> None:
        self.ui.config_mode.currentIndexChanged.connect(self.update_mode_tab)
        self.ui.file_name.editingFinished.connect(self.update_enable_states)
        self.ui.select_file_button.clicked.connect(self.select_file)
        self.ui.show_panel_buffer.clicked.connect(self.show_panel_buffer)
        self.ui.clear_panel_buffer.clicked.connect(self.clear_panel_buffer)
        self.ui.save_panel_buffer.clicked.connect(self.save_panel_buffer)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def setup_combo_box_data(self) -> None:
        item_data = [
            CONFIG_MODE_BORDER,
            CONFIG_MODE_NUMPY,
            CONFIG_MODE_NAME,
        ]
        for i, data in enumerate(item_data):
            self.ui.config_mode.setItemData(i, data)

    def setup_valid_names(self) -> None:
        w = self.ui.selected_name
        w.clear()
        w.addItems(valid_panel_buffer_names())

    def show(self) -> None:
        self.ui.show()

    def on_accepted(self) -> None:
        if self.mode == CONFIG_MODE_NUMPY and self.file_name == '':
            msg = 'Please select a NumPy array file'
            print(msg)
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            self.show()
            return

        if not self.update_config():
            self.show()
            return

        self.accepted.emit()
        HexrdConfig().rerender_needed.emit()
        self.finished.emit(self.ui.result())

    def on_rejected(self) -> None:
        self.rejected.emit()
        self.finished.emit(self.ui.result())

    def select_file(self) -> None:
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Panel Buffer', HexrdConfig().working_dir, 'NPY files (*.npy)'
        )

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            self.file_name = selected_file

    @property
    def file_name(self) -> str:
        return self.ui.file_name.text()

    @file_name.setter
    def file_name(self, v: str) -> None:
        self.ui.file_name.setText(v)
        self.update_enable_states()

    @property
    def x_border(self) -> float:
        return self.ui.border_x_spinbox.value()

    @property
    def y_border(self) -> float:
        return self.ui.border_y_spinbox.value()

    @property
    def widgets(self) -> list[QWidget]:
        return [
            self.ui.file_name,
            self.ui.border_x_spinbox,
            self.ui.border_y_spinbox,
            self.ui.selected_name,
        ]

    @property
    def current_editing_buffer_value(self) -> Any:
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
    def current_saved_buffer_value(self) -> Any:
        return self.detector_config.get('buffer', self.default_buffer)

    @property
    def detector_config(self) -> dict[str, Any]:
        return HexrdConfig().detector(self.detector)

    @property
    def detector_shape(self) -> tuple[int, int]:
        pixels = self.detector_config['pixels']
        return (pixels['rows'], pixels['columns'])

    def _has_meaningful_buffer(self) -> bool:
        """Check if the current saved buffer is non-trivial."""
        buffer = self.current_saved_buffer_value
        if buffer is None:
            return False

        if isinstance(buffer, str):
            return True

        buffer = np.asarray(buffer)
        if buffer.size in (1, 2):
            # Border mode: [0, 0] means no buffer
            return not np.allclose(buffer, 0)

        # 2D array is always meaningful
        return True

    def _prompt_combine_or_replace(self) -> str | None:
        """Show a dialog to choose how to handle the existing buffer.

        Returns the selected option text, or None if canceled.
        """
        dialog = QDialog(self.ui)
        dialog.setWindowTitle('Existing Panel Buffer')
        dialog.setMinimumSize(400, 150)
        layout = QVBoxLayout()
        dialog.setLayout(layout)

        label = QLabel(
            'A panel buffer already exists for this detector.\n'
            'Would you like to replace the existing buffer, or combine them?',
            dialog,
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        options = QComboBox(dialog)
        options.addItem('Replace buffer')
        options.addItem('Union of old and new panel buffers')
        options.addItem('Intersection of old and new panel buffers')
        layout.addWidget(options)

        buttons = (
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box = QDialogButtonBox(buttons, dialog)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if not dialog.exec():
            return None

        return options.currentText()

    def update_config(self) -> bool:
        # Set the new config options on the internal config
        value = self.current_editing_buffer_value
        if value is None:
            return False

        if self._has_meaningful_buffer():
            selection = self._prompt_combine_or_replace()
            if selection is None:
                # Canceled
                return False

            # NOTE: logical_and and logical_or here are applied to
            # the valid-pixel arrays, so they are inverted relative
            # to the union/intersection of the masked regions.
            if selection == 'Union of old and new panel buffers':
                old_2d = self._buffer_as_2d_array(self.current_saved_buffer_value)
                new_2d = self._buffer_as_2d_array(value)
                value = np.logical_and(old_2d, new_2d)
            elif selection == 'Intersection of old and new panel buffers':
                old_2d = self._buffer_as_2d_array(self.current_saved_buffer_value)
                new_2d = self._buffer_as_2d_array(value)
                value = np.logical_or(old_2d, new_2d)

        self.detector_config['buffer'] = value

        if isinstance(value, str):
            # Check if this has ROIs and a group
            # If so, ask if the user wants to apply this setting
            # to all detectors in this group.
            group = HexrdConfig().detector_group(self.detector)
            if HexrdConfig().instrument_has_roi and isinstance(group, str) and group:
                det_keys = HexrdConfig().detectors_in_group(group)
                if len(det_keys) > 1:
                    title = 'Apply to Other Detectors?'
                    msg = (
                        f'Set panel buffer "{value}" to all '
                        f'detectors in the group "{group}"?'
                    )
                    response = QMessageBox.question(self.ui, title, msg)
                    if response == QMessageBox.StandardButton.Yes:
                        for det_key in det_keys:
                            config = HexrdConfig().detector(det_key)
                            config['buffer'] = value

        return True

    def update_gui(self) -> None:
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
                        if np.array_equal(buffer, np.asarray(None)):
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
    def mode(self) -> str:
        return self.ui.config_mode.currentData()

    @mode.setter
    def mode(self, v: str) -> None:
        w = self.ui.config_mode
        for i in range(w.count()):
            if v == w.itemData(i):
                w.setCurrentIndex(i)
                return

        raise Exception(f'Unable to set config mode: {v}')

    def update_mode_tab(self) -> None:
        mode_tab = getattr(self.ui, self.mode + '_tab')
        self.ui.tab_widget.setCurrentWidget(mode_tab)
        self.update_enable_states()

    def update_enable_states(self) -> None:
        editing_value = self.current_editing_buffer_value

        has_numpy_array = False
        if not isinstance(editing_value, str):
            buffer = np.asarray(editing_value)
            has_numpy_array = buffer.size > 2

        self.ui.show_panel_buffer.setEnabled(has_numpy_array)

        # Save is available whenever any buffer is configured
        can_save = editing_value is not None
        self.ui.save_panel_buffer.setEnabled(can_save)

    def clear_panel_buffer(self) -> None:
        # Clear the config options on the internal config
        self.detector_config['buffer'] = self.default_buffer
        self.update_enable_states()
        HexrdConfig().rerender_needed.emit()

    @property
    def default_buffer(self) -> list[float]:
        return [0.0, 0.0]

    def _get_panel(self) -> Detector:
        instr = create_hedm_instrument()
        return instr.detectors[self.detector]

    def _buffer_as_2d_array(self, buffer: Any) -> np.ndarray:
        """Convert any buffer representation to a 2D boolean array."""
        panel = self._get_panel()
        # Temporarily set the panel buffer so panel_buffer_as_2d_array works
        original = panel.panel_buffer
        try:
            if isinstance(buffer, str):
                panel.panel_buffer = buffer
            else:
                panel.panel_buffer = np.asarray(buffer)
            return panel_buffer_as_2d_array(panel)
        finally:
            panel.panel_buffer = original

    def show_panel_buffer(self) -> None:
        buffer = self.current_editing_buffer_value
        if isinstance(buffer, str):
            panel = self._get_panel()
            buffer = panel_buffer_from_str(buffer, panel)
        else:
            buffer = np.asarray(buffer)
            if buffer.size <= 2:
                # We only support showing numpy array buffers currently
                return

        fig, ax = plt.subplots()
        if fig.canvas.manager is not None:
            fig.canvas.manager.set_window_title(f'{self.detector}')
        ax.set_title('Panel Buffer')

        ax.imshow(buffer, vmin=0, vmax=1)
        fig.canvas.draw_idle()
        fig.show()

    def save_panel_buffer(self) -> None:
        selected_file, _ = QFileDialog.getSaveFileName(
            self.ui,
            'Save Panel Buffer',
            HexrdConfig().working_dir,
            'NPY files (*.npy)',
        )

        if not selected_file:
            return

        if not selected_file.endswith('.npy'):
            selected_file += '.npy'

        HexrdConfig().working_dir = os.path.dirname(selected_file)

        buffer = self.current_editing_buffer_value
        if buffer is None:
            return

        array = self._buffer_as_2d_array(buffer)
        np.save(selected_file, array)
        msg = f'Panel buffer saved to "{selected_file}"'
        print(msg)
