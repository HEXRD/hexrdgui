from __future__ import annotations

from typing import Any, TYPE_CHECKING

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from hexrd.material.jcpds import JCPDS_extend

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals

if TYPE_CHECKING:
    from hexrd.material import Material


class PTSliderDialog:

    VAL_TO_SLIDER = 10
    SLIDER_TO_VAL = 1 / VAL_TO_SLIDER

    MIN_PRESSURE = 1e-4
    DEFAULT_PRESSURE = MIN_PRESSURE

    MIN_TEMPERATURE = 0
    DEFAULT_TEMPERATURE = 298

    def __init__(self, material: Material, parent: QWidget | None = None) -> None:
        self.ui = UiLoader().load_file('pt_slider_dialog.ui', parent)

        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.WindowType.Tool)

        self.material = material
        self.title_prefix = self.ui.windowTitle()

        self.update_window_title()
        self.update_gui()
        self.setup_connections()

    def setup_connections(self) -> None:
        for w in self.pt_param_widgets:
            w.valueChanged.connect(self.on_pt_param_widget_changed)

        self.ui.pressure_slider_range.valueChanged.connect(
            self.update_pressure_slider_range
        )
        self.ui.pressure_slider.valueChanged.connect(self.on_pressure_slider_move)
        self.ui.pressure.editingFinished.connect(self.update_pressure_slider_range)
        self.ui.pressure.valueChanged.connect(self.on_pt_change)

        self.ui.temperature_slider_range.valueChanged.connect(
            self.update_temperature_slider_range
        )
        self.ui.temperature_slider.valueChanged.connect(self.on_temperature_slider_move)
        self.ui.temperature.editingFinished.connect(
            self.update_temperature_slider_range
        )
        self.ui.temperature.valueChanged.connect(self.on_pt_change)

        self.ui.read_from_jcpds_button.clicked.connect(self.open_jcpds)

        self.ui.set_ambient_structure_button.clicked.connect(self.set_ambient_structure)

        HexrdConfig().material_renamed.connect(self.update_window_title)

    def on_pt_param_widget_changed(self) -> None:
        self.update_material_from_gui()
        self.on_pt_change()

    @property
    def pt_param_names(self) -> list[str]:
        return [
            'k0',
            'k0p',
            'dk0dt',
            'dk0pdt',
            'alpha_t',
            'dalpha_t_dt',
        ]

    @property
    def pt_param_widgets(self) -> list[Any]:
        return [getattr(self.ui, x) for x in self.pt_param_names]

    @property
    def all_widgets(self) -> list[Any]:
        return [
            *self.pt_param_widgets,
            self.ui.pressure_slider_range,
            self.ui.pressure_slider,
            self.ui.pressure,
            self.ui.temperature_slider_range,
            self.ui.temperature_slider,
            self.ui.temperature,
        ]

    def show(self) -> None:
        self.update_gui()
        self.ui.show()

    def hide(self) -> None:
        self.ui.hide()

    def update_material_from_gui(self) -> None:
        for name in self.pt_param_names:
            setattr(self.material, name, getattr(self.ui, name).value())

    def update_window_title(self) -> None:
        self.ui.setWindowTitle(f'{self.title_prefix}{self.material.name}')

    def update_gui(self) -> None:
        with block_signals(*self.pt_param_widgets):
            for name in self.pt_param_names:
                getattr(self.ui, name).setValue(getattr(self.material, name))

        with block_signals(self.ui.pressure, self.ui.temperature):
            self.pressure = self.material.pressure
            self.temperature = self.material.temperature

        self.update_pressure_slider_range()
        self.update_temperature_slider_range()
        self.update_ambient_structure()

    def update_pressure_slider_range(self) -> None:
        r = self.ui.pressure_slider_range.value() * self.VAL_TO_SLIDER
        v = self.ui.pressure.value() * self.VAL_TO_SLIDER

        min_val = v - r / 2
        max_val = v + r / 2

        if min_val < self.MIN_PRESSURE:
            max_val += self.MIN_PRESSURE - min_val
            min_val = self.MIN_PRESSURE

        self.ui.pressure_slider.setRange(min_val, max_val)
        self.ui.pressure_slider.setValue(v)

    def on_pressure_slider_move(self, v: float) -> None:
        self.pressure = v * self.SLIDER_TO_VAL

    @property
    def pressure(self) -> float:
        return self.ui.pressure.value()

    @pressure.setter
    def pressure(self, v: float) -> None:
        self.ui.pressure.setValue(v)

    def update_temperature_slider_range(self) -> None:
        r = self.ui.temperature_slider_range.value() * self.VAL_TO_SLIDER
        v = self.ui.temperature.value() * self.VAL_TO_SLIDER

        min_val = v - r / 2
        max_val = v + r / 2

        if min_val < self.MIN_TEMPERATURE:
            max_val += self.MIN_TEMPERATURE - min_val
            min_val = self.MIN_TEMPERATURE

        self.ui.temperature_slider.setRange(min_val, max_val)
        self.ui.temperature_slider.setValue(v)

    def on_temperature_slider_move(self, v: float) -> None:
        self.temperature = v * self.SLIDER_TO_VAL

    @property
    def temperature(self) -> float:
        return self.ui.temperature.value()

    @temperature.setter
    def temperature(self, v: float) -> None:
        self.ui.temperature.setValue(v)

    def on_pt_change(self) -> None:
        mat = self.material

        # Compute the lp factor
        lparms = mat.calc_lp_at_PT(self.pressure, self.temperature)
        if np.any(np.isnan(lparms)):
            raise Exception(f'lparms contains nan: {lparms}')

        mat.lparms = lparms
        mat.pressure = self.pressure
        mat.temperature = self.temperature

        self.material_modified()
        self.rerender_overlays()

    def material_modified(self) -> None:
        HexrdConfig().material_modified.emit(self.material.name)

    @property
    def ambient_structure_widgets(self) -> list[Any]:
        names = [
            'a',
            'b',
            'c',
            'alpha',
            'beta',
            'gamma',
        ]
        return [getattr(self.ui, f'ambient_{name}') for name in names]

    def update_ambient_structure(self) -> None:
        lparms0 = self.material.lparms0

        # Convert to angstroms
        lparms0 = [
            *(10 * lparms0[:3]),
            *lparms0[3:],
        ]

        for v, w in zip(lparms0, self.ambient_structure_widgets):
            w.setValue(v)

    def rerender_overlays(self) -> None:
        HexrdConfig().flag_overlay_updates_for_material(self.material.name)
        HexrdConfig().overlay_config_changed.emit()

    def reset_pressure_and_temperature(self) -> None:
        # Set the lattice parameters back to v0
        lparms0 = self.material.lparms0

        # Convert to angstroms
        self.material.latticeParameters = [
            *(10 * lparms0[:3]),
            *lparms0[3:],
        ]

        # Set pressure and temperature back to 0
        with block_signals(self.ui.pressure, self.ui.temperature):
            self.pressure = self.DEFAULT_PRESSURE
            self.temperature = self.DEFAULT_TEMPERATURE

        self.material.pressure = self.pressure
        self.material.temperature = self.temperature

        self.update_gui()
        self.material_modified()

    def open_jcpds(self) -> None:
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui,
            'Select JCPDS File',
            HexrdConfig().working_dir,
            'JCPDS files (*.jcpds)',
        )

        if selected_file:
            self.read_jcpds(selected_file)

    def read_jcpds(self, filename: str) -> None:
        jcpds = JCPDS_extend(filename)
        if not self.validate_jcpds(jcpds):
            return

        self.compare_jcpds_to_material(jcpds)

        # We will always write the pt parameters to the material
        jcpds.write_pt_params_to_material(self.material)

        self.reset_pressure_and_temperature()

    def validate_jcpds(self, jcpds: JCPDS_extend) -> bool:
        if not jcpds.symmetry_matches(self.material):
            msg = (
                f'The JCPDS symmetry "{jcpds.symmetry}" does not match the '
                f'symmetry of the material "{self.material.latticeType}"! '
                'The JCPDS file will not be loaded.'
            )
            HexrdConfig().logger.error(msg)
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return False

        return True

    def compare_jcpds_to_material(self, jcpds: JCPDS_extend) -> bool:
        # Check for differences with the JCPDS and the material,
        # and update one of them if needed.

        if not jcpds.matches_material(self.material):
            msg = (
                'The JCPDS parameters do not exactly match that of the '
                f'material "{self.material.name}". Update the material '
                'parameters to match?'
            )
            if QMessageBox.question(self.ui, 'HEXRD', msg) == QMessageBox.StandardButton.Yes:
                jcpds.write_lattice_params_to_material(self.material)
                self.rerender_overlays()

        return True

    def set_ambient_structure(self) -> None:
        self.material.reset_v0()
        self.reset_pressure_and_temperature()
