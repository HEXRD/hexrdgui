from __future__ import annotations

import functools
import math

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialogButtonBox
from hexrdgui.masking.constants import MaskType
from hexrdgui.masking.mask_manager import MaskManager

from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.dialog import add_help_url

MAX_ROWS = 2


class ThresholdMaskDialog(QObject):

    # Mask has been applied
    mask_applied = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file(
            'threshold_mask_dialog.ui', parent  # type: ignore[arg-type]
        )
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.WindowType.Tool)

        add_help_url(self.ui.button_box, 'configuration/masking/#threshold')

        self.values: list[float] = []

        self.setup_gui()
        self.setup_connections()

    def show(self) -> None:
        self.setup_gui()
        self.ui.show()

    def setup_gui(self, reset: bool = False) -> None:
        threshold_mask = MaskManager().threshold_mask
        if reset or not threshold_mask:
            vals = []
        else:
            vals = threshold_mask.data

        val = vals[0] if len(vals) > 0 else -math.inf
        self.ui.first_value.setValue(val)

        val = vals[1] if len(vals) > 1 else math.inf
        self.ui.second_value.setValue(val)

    def setup_connections(self) -> None:
        apply_button = self.ui.button_box.button(QDialogButtonBox.StandardButton.Apply)
        apply_button.clicked.connect(self.accept)
        reset_button = self.ui.button_box.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        reset_button.clicked.connect(functools.partial(self.setup_gui, reset=True))

    def gather_input(self) -> None:
        self.values.clear()
        self.values.append(self.ui.first_value.value())
        self.values.append(self.ui.second_value.value())

    def accept(self) -> None:
        self.gather_input()
        threshold_mask = MaskManager().threshold_mask
        if threshold_mask is None:
            MaskManager().add_mask(self.values, MaskType.threshold, name='threshold')
        else:
            threshold_mask.data = self.values
        self.mask_applied.emit()
