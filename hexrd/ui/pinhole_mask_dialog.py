from hexrd.ui.ui_loader import UiLoader


class PinholeMaskDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('pinhole_mask_dialog.ui', parent)

    def exec_(self):
        return self.ui.exec_()

    @property
    def pinhole_radius(self):
        return self.ui.pinhole_radius.value() * 1e-3

    @property
    def pinhole_thickness(self):
        return self.ui.pinhole_thickness.value() * 1e-3
