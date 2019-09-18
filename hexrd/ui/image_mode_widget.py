from PySide2.QtCore import QObject, Signal

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class ImageModeWidget(QObject):

    # The string indicates which tab was selected
    tab_changed = Signal(str)

    def __init__(self, parent=None):
        super(ImageModeWidget, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('image_mode_widget.ui', parent)

        self.setup_connections()
        self.update_gui_from_config()

    def setup_connections(self):
        self.ui.raw_tabbed_view.toggled.connect(HexrdConfig().set_tab_images)
        self.ui.raw_show_saturation.toggled.connect(
            HexrdConfig().set_show_saturation_level)
        self.ui.cartesian_pixel_size.valueChanged.connect(
            HexrdConfig()._set_cartesian_pixel_size)
        self.ui.cartesian_virtual_plane_distance.valueChanged.connect(
            HexrdConfig().set_cartesian_virtual_plane_distance)
        self.ui.cartesian_plane_normal_rotate_x.valueChanged.connect(
            HexrdConfig().set_cartesian_plane_normal_rotate_x)
        self.ui.cartesian_plane_normal_rotate_y.valueChanged.connect(
            HexrdConfig().set_cartesian_plane_normal_rotate_y)
        self.ui.polar_pixel_size_tth.valueChanged.connect(
            HexrdConfig()._set_polar_pixel_size_tth)
        self.ui.polar_pixel_size_eta.valueChanged.connect(
            HexrdConfig()._set_polar_pixel_size_eta)
        self.ui.polar_res_tth_min.valueChanged.connect(
            HexrdConfig().set_polar_res_tth_min)
        self.ui.polar_res_tth_max.valueChanged.connect(
            HexrdConfig().set_polar_res_tth_max)

        self.ui.tab_widget.currentChanged.connect(self.currentChanged)

    def currentChanged(self, index):
        s = self.ui.tab_widget.tabText(index)
        self.tab_changed.emit(s)

    def all_widgets(self):
        widgets = [
            self.ui.raw_tabbed_view,
            self.ui.raw_show_saturation,
            self.ui.cartesian_pixel_size,
            self.ui.cartesian_virtual_plane_distance,
            self.ui.cartesian_plane_normal_rotate_x,
            self.ui.cartesian_plane_normal_rotate_y,
            self.ui.polar_pixel_size_tth,
            self.ui.polar_pixel_size_eta,
            self.ui.polar_res_tth_min,
            self.ui.polar_res_tth_max
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
            self.ui.cartesian_virtual_plane_distance.setValue(
                HexrdConfig().cartesian_virtual_plane_distance)
            self.ui.cartesian_plane_normal_rotate_x.setValue(
                HexrdConfig().cartesian_plane_normal_rotate_x)
            self.ui.cartesian_plane_normal_rotate_y.setValue(
                HexrdConfig().cartesian_plane_normal_rotate_y)
            self.ui.polar_pixel_size_tth.setValue(
                HexrdConfig().polar_pixel_size_tth)
            self.ui.polar_pixel_size_eta.setValue(
                HexrdConfig().polar_pixel_size_eta)
            self.ui.polar_res_tth_min.setValue(
                HexrdConfig().polar_res_tth_min)
            self.ui.polar_res_tth_max.setValue(
                HexrdConfig().polar_res_tth_max)
        finally:
            self.unblock_widgets(block_list)
