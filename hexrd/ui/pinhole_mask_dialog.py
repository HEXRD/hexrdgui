from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialogButtonBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class PinholeMaskDialog(QObject):

    # Arguments are radius, thickness
    apply_clicked = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('pinhole_mask_dialog.ui', parent)
        self.load_settings()
        self.setup_connections()

    def setup_connections(self):
        apply_button = self.ui.button_box.button(QDialogButtonBox.Apply)
        apply_button.clicked.connect(self.on_apply_clicked)

    def show(self):
        return self.ui.show()

    def on_apply_clicked(self):
        self.save_settings()
        self.apply_clicked.emit(self.pinhole_radius, self.pinhole_thickness)

    @property
    def settings(self):
        return HexrdConfig().config['image']['pinhole_mask_settings']

    def load_settings(self):
        for name, value in self.settings.items():
            setattr(self, name, value)

    def save_settings(self):
        for name in self.settings:
            self.settings[name] = getattr(self, name)

    @property
    def pinhole_radius(self):
        return self.ui.pinhole_radius.value() * 1e-3

    @property
    def pinhole_thickness(self):
        return self.ui.pinhole_thickness.value() * 1e-3

    @pinhole_radius.setter
    def pinhole_radius(self, v):
        self.ui.pinhole_radius.setValue(v / 1e-3)

    @pinhole_thickness.setter
    def pinhole_thickness(self, v):
        self.ui.pinhole_thickness.setValue(v / 1e-3)
