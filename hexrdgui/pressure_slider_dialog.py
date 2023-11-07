from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from hexrd.material.jcpds import JCPDS_extend

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader


class PressureSliderDialog:

    VAL_TO_SLIDER = 10
    SLIDER_TO_VAL = 1 / VAL_TO_SLIDER

    MIN_PRESSURE = 1e-4

    def __init__(self, material, parent=None):
        self.ui = UiLoader().load_file('pressure_slider_dialog.ui', parent)

        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.material = material
        self.jcpds = JCPDS_extend()
        self.jcpds.load_from_material(self.material)

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.k0.valueChanged.connect(self.update_jcpds_from_gui)
        self.ui.k0p.valueChanged.connect(self.update_jcpds_from_gui)
        self.ui.pressure_slider_range.valueChanged.connect(
            self.update_slider_range)
        self.ui.pressure_slider.sliderMoved.connect(self.on_slider_move)
        self.ui.pressure.editingFinished.connect(self.update_slider_range)
        self.ui.pressure.valueChanged.connect(self.on_pressure_change)
        self.ui.read_from_jcpds_button.clicked.connect(
            self.open_jcpds)

    def show(self):
        self.update_gui()
        self.ui.show()

    def update_jcpds_from_gui(self):
        self.jcpds.k0 = self.ui.k0.value()
        self.jcpds.k0p = self.ui.k0p.value()

    def update_gui(self):
        self.ui.k0.setValue(self.jcpds.k0)
        self.ui.k0p.setValue(self.jcpds.k0p)
        self.update_slider_range()

    def update_slider_range(self):
        r = self.ui.pressure_slider_range.value() * self.VAL_TO_SLIDER
        v = self.ui.pressure.value() * self.VAL_TO_SLIDER

        min_val = v - r / 2
        max_val = v + r / 2

        if min_val < self.MIN_PRESSURE:
            max_val += (self.MIN_PRESSURE - min_val)
            min_val = self.MIN_PRESSURE

        self.ui.pressure_slider.setRange(min_val, max_val)
        self.ui.pressure_slider.setValue(v)

    def on_slider_move(self, v):
        self.pressure = v * self.SLIDER_TO_VAL

    @property
    def pressure(self):
        return self.ui.pressure.value()

    @pressure.setter
    def pressure(self, v):
        self.ui.pressure.setValue(v)

    def on_pressure_change(self):
        lp = self.jcpds.calc_lp_at_PT(self.pressure)
        self.material.latticeParameters = lp
        self.rerender_overlays()

    def rerender_overlays(self):
        HexrdConfig().flag_overlay_updates_for_material(self.material.name)
        HexrdConfig().overlay_config_changed.emit()

    def open_jcpds(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Select JCPDS File', HexrdConfig().working_dir,
            'JCPDS files (*.jcpds)')

        if selected_file:
            self.read_jcpds(selected_file)

    def read_jcpds(self, filename):
        self.jcpds = JCPDS_extend(filename)
        if not self.validate_jcpds():
            self.jcpds = None
            return

        self.compare_jcpds_to_material()
        self.update_gui()

    def validate_jcpds(self):
        if not self.jcpds.symmetry_matches(self.material):
            msg = (
                f'The JCPDS symmetry "{self.symmetry}" does not match the '
                f'symmetry of the material "{self.material.latticeType}"! '
                'The JCPDS file will not be loaded.'
            )
            HexrdConfig().logger.error(msg)
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return False

        return True

    def compare_jcpds_to_material(self):
        # Check for differences with the JCPDS and the material,
        # and update one of them if needed.

        if not self.jcpds.matches_material(self.material):
            msg = (
                'The JCPDS parameters do not exactly match that of the '
                f'material "{self.material.name}". Update the material '
                'parameters to match?'
            )
            if QMessageBox.question(self.ui, 'HEXRD', msg) == QMessageBox.Yes:
                self.jcpds.write_to_material(self.material)
                self.rerender_overlays()
            else:
                self.jcpds.load_from_material(self.material)

        return True
