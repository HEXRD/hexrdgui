from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader


class MedianFilterDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file(
            'median_filter_intensity_correction_dialog.ui',
            parent
        )

        self.ui.kernel_size.setValue(self.kernel_size)

        self.update_gui()
        self.setup_connections()

    def update_gui(self):
        # Cannot exceed array dimensions
        img = HexrdConfig().image(HexrdConfig().detector_names[0], 0)
        upper_bound = min(img.shape[0], img.shape[1])
        self.ui.kernel_size.setMaximum(upper_bound)

    def setup_connections(self):
        self.ui.button_box.accepted.connect(self.accept_changes)

    def show(self):
        self.ui.show()

    def exec(self):
        return self.ui.exec()

    @property
    def kernel_size(self):
        return HexrdConfig().median_filter_kernel_size

    def accept_changes(self):
        value = self.ui.kernel_size.value()
        HexrdConfig().median_filter_kernel_size = value
