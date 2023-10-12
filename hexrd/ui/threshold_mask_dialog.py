import functools
import math

import numpy as np

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialogButtonBox
from hexrd.ui.create_raw_mask import apply_threshold_mask
from hexrd.ui.hexrd_config import HexrdConfig

from hexrd.ui.ui_loader import UiLoader

MAX_ROWS = 2


class ThresholdMaskDialog(QObject):

    # Mask has been applied
    mask_applied = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('threshold_mask_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.values = []

        self.setup_gui()
        self.setup_connections()

    def show(self):
        self.setup_gui()
        self.ui.show()

    def setup_gui(self, reset=False):
        vals = [] if reset else HexrdConfig().threshold_values

        val = vals[0] if len(vals) > 0 else -math.inf
        self.ui.first_value.setValue(val)

        val = vals[1] if len(vals) > 1 else math.inf
        self.ui.second_value.setValue(val)

    def setup_connections(self):
        apply_button = self.ui.button_box.button(QDialogButtonBox.Apply)
        apply_button.clicked.connect(self.accept)
        reset_button = self.ui.button_box.button(QDialogButtonBox.RestoreDefaults)
        reset_button.clicked.connect(
            functools.partial(self.setup_gui, reset=True))

        HexrdConfig().mgr_threshold_mask_changed.connect(self.setup_gui)

    def gather_input(self):
        self.values.clear()
        self.values.append(self.ui.first_value.value())
        self.values.append(self.ui.second_value.value())

    def accept(self):
        self.gather_input()
        HexrdConfig().threshold_values = self.values
        apply_threshold_mask()
        self.mask_applied.emit()
