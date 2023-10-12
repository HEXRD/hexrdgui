from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialogButtonBox

from hexrd.ui.ui_loader import UiLoader


class ReflectionsSelectionHelper(QObject):

    apply_clicked = Signal()

    def __init__(self, material, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('reflections_selection_helper.ui', parent)

        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self._material = material

        self.update_material_name()

        self.setup_connections()

    def setup_connections(self):
        apply_button = self.ui.button_box.button(QDialogButtonBox.Apply)
        apply_button.clicked.connect(self.on_apply_clicked)

    def show(self):
        return self.ui.show()

    def on_apply_clicked(self):
        self.apply_clicked.emit()

    @property
    def title_prefix(self):
        return 'Reflections Selection: '

    @property
    def material(self):
        return self._material

    @material.setter
    def material(self, mat):
        if mat is self.material:
            return

        self._material = mat
        self.update_material_name()

    def update_material_name(self):
        self.ui.setWindowTitle(f'{self.title_prefix}{self.material.name}')

    @property
    def min_sfac_enabled(self):
        return self.ui.min_sfac_enabled.isChecked()

    @property
    def min_sfac_value(self):
        return self.ui.min_sfac_value.value()

    @property
    def min_sfac(self):
        if not self.min_sfac_enabled:
            return None

        return self.min_sfac_value

    @property
    def max_sfac_enabled(self):
        return self.ui.max_sfac_enabled.isChecked()

    @property
    def max_sfac_value(self):
        return self.ui.max_sfac_value.value()

    @property
    def max_sfac(self):
        if not self.max_sfac_enabled:
            return None

        return self.max_sfac_value
