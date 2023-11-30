from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from hexrd.material.jcpds import JCPDS_extend

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class PTSliderDialog:

    VAL_TO_SLIDER = 10
    SLIDER_TO_VAL = 1 / VAL_TO_SLIDER

    MIN_PRESSURE = 1e-4
    MIN_TEMPERATURE = 0

    def __init__(self, material, parent=None):
        self.ui = UiLoader().load_file('pt_slider_dialog.ui', parent)

        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.material = material
        self.title_prefix = self.ui.windowTitle()

        self.update_window_title()
        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        for w in self.pt_param_widgets:
            w.valueChanged.connect(self.on_pt_param_widget_changed)

        self.ui.pressure_slider_range.valueChanged.connect(
            self.update_pressure_slider_range)
        self.ui.pressure_slider.valueChanged.connect(
            self.on_pressure_slider_move)
        self.ui.pressure.editingFinished.connect(
            self.update_pressure_slider_range)
        self.ui.pressure.valueChanged.connect(self.on_pt_change)

        self.ui.temperature_slider_range.valueChanged.connect(
            self.update_temperature_slider_range)
        self.ui.temperature_slider.valueChanged.connect(
            self.on_temperature_slider_move)
        self.ui.temperature.editingFinished.connect(
            self.update_temperature_slider_range)
        self.ui.temperature.valueChanged.connect(self.on_pt_change)

        self.ui.read_from_jcpds_button.clicked.connect(
            self.open_jcpds)

        HexrdConfig().material_renamed.connect(self.update_window_title)

    def on_pt_param_widget_changed(self):
        self.update_material_from_gui()
        self.on_pt_change()

    @property
    def pt_param_names(self):
        return [
            'k0',
            'k0p',
            'dk0dt',
            'dk0pdt',
            'alpha_t',
            'dalpha_t_dt',
        ]

    @property
    def pt_param_widgets(self):
        return [getattr(self.ui, x) for x in self.pt_param_names]

    @property
    def all_widgets(self):
        return [
            *self.pt_param_widgets,
            self.ui.pressure_slider_range,
            self.ui.pressure_slider,
            self.ui.pressure,
            self.ui.temperature_slider_range,
            self.ui.temperature_slider,
            self.ui.temperature,
        ]

    def show(self):
        self.update_gui()
        self.ui.show()

    def hide(self):
        self.ui.hide()

    def update_material_from_gui(self):
        for name in self.pt_param_names:
            setattr(self.material, name, getattr(self.ui, name).value())

    def update_window_title(self):
        self.ui.setWindowTitle(f'{self.title_prefix}{self.material.name}')

    def update_gui(self):
        with block_signals(*self.pt_param_widgets):
            for name in self.pt_param_names:
                getattr(self.ui, name).setValue(getattr(self.material, name))

        self.update_pressure_slider_range()
        self.update_temperature_slider_range()

    def update_pressure_slider_range(self):
        r = self.ui.pressure_slider_range.value() * self.VAL_TO_SLIDER
        v = self.ui.pressure.value() * self.VAL_TO_SLIDER

        min_val = v - r / 2
        max_val = v + r / 2

        if min_val < self.MIN_PRESSURE:
            max_val += (self.MIN_PRESSURE - min_val)
            min_val = self.MIN_PRESSURE

        self.ui.pressure_slider.setRange(min_val, max_val)
        self.ui.pressure_slider.setValue(v)

    def on_pressure_slider_move(self, v):
        self.pressure = v * self.SLIDER_TO_VAL

    @property
    def pressure(self):
        return self.ui.pressure.value()

    @pressure.setter
    def pressure(self, v):
        self.ui.pressure.setValue(v)

    def update_temperature_slider_range(self):
        r = self.ui.temperature_slider_range.value() * self.VAL_TO_SLIDER
        v = self.ui.temperature.value() * self.VAL_TO_SLIDER

        min_val = v - r / 2
        max_val = v + r / 2

        if min_val < self.MIN_TEMPERATURE:
            max_val += (self.MIN_TEMPERATURE - min_val)
            min_val = self.MIN_TEMPERATURE

        self.ui.temperature_slider.setRange(min_val, max_val)
        self.ui.temperature_slider.setValue(v)

    def on_temperature_slider_move(self, v):
        self.temperature = v * self.SLIDER_TO_VAL

    @property
    def temperature(self):
        return self.ui.temperature.value()

    @temperature.setter
    def temperature(self, v):
        self.ui.temperature.setValue(v)

    def on_pt_change(self):
        lp = self.material.calc_lp_at_PT(self.pressure, self.temperature)
        self.material.latticeParameters = lp
        self.material_modified()
        self.rerender_overlays()

    def material_modified(self):
        HexrdConfig().material_modified.emit(self.material.name)

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
        jcpds = JCPDS_extend(filename)
        if not self.validate_jcpds(jcpds):
            return

        self.compare_jcpds_to_material(jcpds)

        # We will always write the pt parameters to the material
        jcpds.write_pt_params_to_material(self.material)

        # Set pressure and temperature back to 0
        with block_signals(self.ui.pressure, self.ui.temperature):
            self.pressure = self.MIN_PRESSURE
            self.temperature = self.MIN_TEMPERATURE

        self.update_gui()

        # Trigger an update
        self.on_pt_change()

    def validate_jcpds(self, jcpds):
        if not jcpds.symmetry_matches(self.material):
            msg = (
                f'The JCPDS symmetry "{self.symmetry}" does not match the '
                f'symmetry of the material "{self.material.latticeType}"! '
                'The JCPDS file will not be loaded.'
            )
            HexrdConfig().logger.error(msg)
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return False

        return True

    def compare_jcpds_to_material(self, jcpds):
        # Check for differences with the JCPDS and the material,
        # and update one of them if needed.

        if not jcpds.matches_material(self.material):
            msg = (
                'The JCPDS parameters do not exactly match that of the '
                f'material "{self.material.name}". Update the material '
                'parameters to match?'
            )
            if QMessageBox.question(self.ui, 'HEXRD', msg) == QMessageBox.Yes:
                jcpds.write_lattice_params_to_material(self.material)
                self.rerender_overlays()

        return True
