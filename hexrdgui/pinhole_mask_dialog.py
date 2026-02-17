from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialogButtonBox

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.dialog import add_help_url


class PinholeMaskDialog(QObject):

    # Arguments are radius, thickness
    apply_clicked = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file(
            'pinhole_mask_dialog.ui', parent  # type: ignore[arg-type]
        )

        add_help_url(self.ui.button_box, 'configuration/masking/#pinhole')

        self.set_values()
        self.setup_connections()

    def setup_connections(self) -> None:
        apply_button = self.ui.button_box.button(QDialogButtonBox.StandardButton.Apply)
        apply_button.clicked.connect(self.on_apply_clicked)
        HexrdConfig().physics_package_modified.connect(self.set_values)

    def show(self) -> None:
        return self.ui.show()

    def on_apply_clicked(self) -> None:
        self.save_settings()
        self.apply_clicked.emit()

    @property
    def settings(self) -> dict:
        return HexrdConfig().config['image']['pinhole_mask_settings']

    def set_values(self) -> None:
        physics_package = HexrdConfig().physics_package
        assert physics_package is not None
        self.ui.pinhole_diameter.setValue(physics_package.pinhole_diameter)
        self.ui.pinhole_thickness.setValue(physics_package.pinhole_thickness)

    def save_settings(self) -> None:
        for name in self.settings:
            self.settings[name] = getattr(self, name)

    @property
    def pinhole_diameter(self) -> float:
        physics_package = HexrdConfig().physics_package
        assert physics_package is not None
        return physics_package.pinhole_diameter

    @property
    def pinhole_thickness(self) -> float:
        physics_package = HexrdConfig().physics_package
        assert physics_package is not None
        return physics_package.pinhole_thickness
