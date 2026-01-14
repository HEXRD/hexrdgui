from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialogButtonBox

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.dialog import add_help_url


class PinholeMaskDialog(QObject):

    # Arguments are radius, thickness
    apply_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('pinhole_mask_dialog.ui', parent)

        add_help_url(self.ui.button_box, 'configuration/masking/#pinhole')

        self.set_values()
        self.setup_connections()

    def setup_connections(self):
        apply_button = self.ui.button_box.button(QDialogButtonBox.Apply)
        apply_button.clicked.connect(self.on_apply_clicked)
        HexrdConfig().physics_package_modified.connect(self.set_values)

    def show(self):
        return self.ui.show()

    def on_apply_clicked(self):
        self.save_settings()
        self.apply_clicked.emit()

    @property
    def settings(self):
        return HexrdConfig().config['image']['pinhole_mask_settings']

    def set_values(self):
        self.ui.pinhole_diameter.setValue(
            HexrdConfig().physics_package.pinhole_diameter
        )
        self.ui.pinhole_thickness.setValue(
            HexrdConfig().physics_package.pinhole_thickness
        )

    def save_settings(self):
        for name in self.settings:
            self.settings[name] = getattr(self, name)

    @property
    def pinhole_diameter(self):
        return HexrdConfig().physics_package.pinhole_diameter

    @property
    def pinhole_thickness(self):
        return HexrdConfig().physics_package.pinhole_thickness
