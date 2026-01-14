from PySide6.QtWidgets import QMessageBox

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader


class MedianFilterDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file(
            'median_filter_intensity_correction_dialog.ui', parent
        )

        self.ui.kernel_size.setValue(self.kernel_size)

        self.update_gui()
        self.setup_connections()

    def update_gui(self):
        # Cannot exceed array dimensions and must be odd
        imgs = HexrdConfig().raw_images_dict.values()
        upper_bound = min([min(*img.shape) for img in imgs])
        if upper_bound % 2 == 0:
            upper_bound -= 1
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
        if value % 2 == 0:
            value -= 1
            msg = f'Value must be odd. Kernel size has been reset to {value}'
            QMessageBox.warning(self.ui.parent(), 'WARNING', msg)

        HexrdConfig().median_filter_kernel_size = value
