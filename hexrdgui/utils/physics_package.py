from PySide6.QtWidgets import QMessageBox

from hexrdgui.hexrd_config import HexrdConfig


def ask_to_create_physics_package_if_missing() -> bool:
    if HexrdConfig().has_physics_package:
        return True

    msg = (
        'This operation requires a physics package. '
        'Would you like to create one?'
    )
    if QMessageBox.question(None, 'HEXRD', msg) == QMessageBox.Yes:
        HexrdConfig().create_default_physics_package()
        return True

    return False
