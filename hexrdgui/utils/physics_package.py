from PySide6.QtWidgets import QMessageBox


def ask_to_create_physics_package_if_missing() -> bool:
    from hexrdgui.hexrd_config import HexrdConfig  # Avoid circular import

    if HexrdConfig().physics_package is not None:
        return True

    msg = (
        'This operation requires a physics package. '
        'Would you like to create one?'
    )
    if QMessageBox.question(None, 'HEXRD', msg) == QMessageBox.Yes:
        HexrdConfig().create_default_physics_package()
        return True

    return False
