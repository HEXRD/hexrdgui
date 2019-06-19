from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader

class ResolutionEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('resolution_editor.ui', parent)

        self.setup_connections()
        self.update_gui_from_config()

    def all_widgets(self):
        widgets = [
            self.ui.cartesian_pixel_size,
            self.ui.polar_pixel_size,
            self.ui.polar_pixel_size_tth,
            self.ui.polar_pixel_size_eta
        ]

        return widgets

    def block_widgets(self):
        previous = []
        for widget in self.all_widgets():
            previous.append(widget.blockSignals(True))

        return previous

    def unblock_widgets(self, previous):
        for widget, block in zip(self.all_widgets(), previous):
            widget.blockSignals(block)

    def update_gui_from_config(self):
        block_list = self.block_widgets()
        try:
            self.ui.cartesian_pixel_size.setValue(
                HexrdConfig().cartesian_pixel_size)
            self.ui.polar_pixel_size.setValue(
                HexrdConfig().polar_pixel_size)
            self.ui.polar_pixel_size_tth.setValue(
                HexrdConfig().polar_pixel_size_tth)
            self.ui.polar_pixel_size_eta.setValue(
                HexrdConfig().polar_pixel_size_eta)
        finally:
            self.unblock_widgets(block_list)

    def setup_connections(self):
        self.ui.cartesian_pixel_size.valueChanged.connect(
            HexrdConfig()._set_cartesian_pixel_size)
        self.ui.polar_pixel_size.valueChanged.connect(
            HexrdConfig()._set_polar_pixel_size)
        self.ui.polar_pixel_size_tth.valueChanged.connect(
            HexrdConfig()._set_polar_pixel_size_tth)
        self.ui.polar_pixel_size_eta.valueChanged.connect(
            HexrdConfig()._set_polar_pixel_size_eta)
