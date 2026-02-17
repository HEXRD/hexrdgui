from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialogButtonBox, QWidget

from hexrdgui.ui_loader import UiLoader

if TYPE_CHECKING:
    from hexrd.material import Material


class ReflectionsSelectionHelper(QObject):

    apply_clicked = Signal()

    def __init__(self, material: Material, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('reflections_selection_helper.ui', parent)

        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.WindowType.Tool)

        self._material = material

        self.update_material_name()

        self.setup_connections()

    def setup_connections(self) -> None:
        apply_button = self.ui.button_box.button(QDialogButtonBox.StandardButton.Apply)
        apply_button.clicked.connect(self.on_apply_clicked)

    def show(self) -> None:
        return self.ui.show()

    def on_apply_clicked(self) -> None:
        self.apply_clicked.emit()

    @property
    def title_prefix(self) -> str:
        return 'Reflections Selection: '

    @property
    def material(self) -> Material:
        return self._material

    @material.setter
    def material(self, mat: Material) -> None:
        if mat is self.material:
            return

        self._material = mat
        self.update_material_name()

    def update_material_name(self) -> None:
        self.ui.setWindowTitle(f'{self.title_prefix}{self.material.name}')

    @property
    def min_sfac_enabled(self) -> bool:
        return self.ui.min_sfac_enabled.isChecked()

    @property
    def min_sfac_value(self) -> float:
        return self.ui.min_sfac_value.value()

    @property
    def min_sfac(self) -> float | None:
        if not self.min_sfac_enabled:
            return None

        return self.min_sfac_value

    @property
    def max_sfac_enabled(self) -> bool:
        return self.ui.max_sfac_enabled.isChecked()

    @property
    def max_sfac_value(self) -> float:
        return self.ui.max_sfac_value.value()

    @property
    def max_sfac(self) -> float | None:
        if not self.max_sfac_enabled:
            return None

        return self.max_sfac_value
