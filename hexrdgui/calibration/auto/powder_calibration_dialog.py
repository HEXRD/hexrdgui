from __future__ import annotations

from typing import Any, TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QWidget

import numpy as np

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader

if TYPE_CHECKING:
    from hexrd.material import Material


class PowderCalibrationDialog:
    def __init__(self, material: Material, parent: QWidget | None = None) -> None:
        loader = UiLoader()
        self.ui = loader.load_file('powder_calibration_dialog.ui', parent)

        self.material = material

        self.setup_combo_boxes()
        self.setup_connections()
        self.update_gui()

    def setup_combo_boxes(self) -> None:
        self.ui.peak_fit_type.clear()
        for t in peak_types:
            label = peak_type_to_label(t)
            self.ui.peak_fit_type.addItem(label, t)

        self.ui.background_type.clear()
        for t in background_types:
            label = background_type_to_label(t)
            self.ui.background_type.addItem(label, t)

    def setup_connections(self) -> None:
        # Show/hide the WPPF asymmetry group based on selected peak fit type.
        self.ui.peak_fit_type.currentIndexChanged.connect(
            self.update_use_wppf_asymmetry_visibility
        )
        self.ui.populate_from_wppf_button.clicked.connect(
            self.populate_asymmetry_from_wppf
        )

    def update_use_wppf_asymmetry_visibility(self) -> None:
        # The asymmetry parameters only make sense for the pink-beam profile.
        visible = self.peak_fit_type == 'pink_beam_dcs'
        self.ui.use_wppf_asymmetry_group.setVisible(visible)

    def populate_asymmetry_from_wppf(self) -> None:
        wppf_params = (
            HexrdConfig().config.get('calibration', {})
            .get('wppf', {})
            .get('params_dict', {})
        )
        missing = [
            k for k in ('alpha0', 'alpha1', 'beta0', 'beta1') if k not in wppf_params
        ]
        if missing:
            QMessageBox.warning(
                self.ui,
                'HEXRD',
                'Could not find pink-beam asymmetry parameters from a '
                'previous WPPF run. Missing: ' + ', '.join(missing) + '.\n\n'
                'Run a WPPF refinement with the pvpink peak shape first.',
            )
            return

        self.alpha0 = float(wppf_params['alpha0']['value'])
        self.alpha1 = float(wppf_params['alpha1']['value'])
        self.beta0 = float(wppf_params['beta0']['value'])
        self.beta1 = float(wppf_params['beta1']['value'])

    def update_gui(self) -> None:
        if self.tth_tol is None:
            default = 0.125
            msg = f'Powder overlay width is required.\n\nSetting to default: {default}°'
            QMessageBox.warning(self.ui.parent(), 'HEXRD', msg)
            self.tth_tol = default

        options = HexrdConfig().config['calibration']['powder']

        self.ui.tth_tolerance.setValue(self.tth_tol)
        self.ui.eta_tolerance.setValue(options['eta_tol'])
        self.ui.fit_tth_tol.setValue(options['fit_tth_tol'])
        self.ui.int_cutoff.setValue(options['int_cutoff'])

        self.auto_guess_initial_fwhm = options['auto_guess_initial_fwhm']
        self.initial_fwhm = options['initial_fwhm']

        self.peak_fit_type = options['pk_type']
        self.background_type = options['bg_type']

        # Asymmetry group (may not exist in older configs).
        pink_cfg = options.get('fixed_pink_asymmetry') or {}
        self.use_wppf_asymmetry = bool(pink_cfg.get('enabled', False))
        self.alpha0 = float(pink_cfg.get('alpha0', 14.4))
        self.alpha1 = float(pink_cfg.get('alpha1', 0.0))
        self.beta0 = float(pink_cfg.get('beta0', 3.016))
        self.beta1 = float(pink_cfg.get('beta1', -7.94))

        # Make sure the group's visibility matches the current pk type.
        self.update_use_wppf_asymmetry_visibility()

    def update_config(self) -> None:
        options = HexrdConfig().config['calibration']['powder']
        self.tth_tol = self.ui.tth_tolerance.value()
        options['eta_tol'] = self.ui.eta_tolerance.value()
        options['fit_tth_tol'] = self.ui.fit_tth_tol.value()
        options['int_cutoff'] = self.ui.int_cutoff.value()

        options['auto_guess_initial_fwhm'] = self.auto_guess_initial_fwhm
        options['initial_fwhm'] = self.initial_fwhm

        options['pk_type'] = self.peak_fit_type
        options['bg_type'] = self.background_type

        options['fixed_pink_asymmetry'] = {
            'enabled': self.use_wppf_asymmetry,
            'alpha0': self.alpha0,
            'alpha1': self.alpha1,
            'beta0': self.beta0,
            'beta1': self.beta1,
        }

    def exec(self) -> bool:
        if not self.ui.exec():
            return False

        self.update_config()
        return True

    @property
    def auto_guess_initial_fwhm(self) -> bool:
        return self.ui.auto_guess_initial_fwhm.isChecked()

    @auto_guess_initial_fwhm.setter
    def auto_guess_initial_fwhm(self, b: bool) -> None:
        self.ui.auto_guess_initial_fwhm.setChecked(b)

    @property
    def initial_fwhm(self) -> float:
        return self.ui.initial_fwhm.value()

    @initial_fwhm.setter
    def initial_fwhm(self, v: float) -> None:
        self.ui.initial_fwhm.setValue(v)

    @property
    def tth_tol(self) -> float | None:
        tth_width = self.material.planeData.tThWidth
        return None if tth_width is None else np.degrees(tth_width)

    @tth_tol.setter
    def tth_tol(self, v: float) -> None:
        v = np.radians(v)
        if self.material.planeData.tThWidth == v:
            # Just return...
            return

        self.material.planeData.tThWidth = v
        HexrdConfig().material_tth_width_modified.emit(self.material.name)
        HexrdConfig().flag_overlay_updates_for_material(self.material.name)
        HexrdConfig().overlay_config_changed.emit()

    @property
    def peak_fit_type(self) -> str:
        return self.ui.peak_fit_type.currentData()

    @peak_fit_type.setter
    def peak_fit_type(self, v: str) -> None:
        w = self.ui.peak_fit_type
        found = False
        for i in range(w.count()):
            if w.itemData(i) == v:
                found = True
                w.setCurrentIndex(i)
                break

        if not found:
            raise Exception(f'Unknown peak fit type: {v}')

    @property
    def background_type(self) -> str:
        return self.ui.background_type.currentData()

    @background_type.setter
    def background_type(self, v: str) -> None:
        w = self.ui.background_type
        found = False
        for i in range(w.count()):
            if w.itemData(i) == v:
                found = True
                w.setCurrentIndex(i)
                break

        if not found:
            raise Exception(f'Unknown background type: {v}')

    @property
    def use_wppf_asymmetry(self) -> bool:
        return self.ui.use_wppf_asymmetry_group.isChecked()

    @use_wppf_asymmetry.setter
    def use_wppf_asymmetry(self, b: bool) -> None:
        self.ui.use_wppf_asymmetry_group.setChecked(b)

    @property
    def alpha0(self) -> float:
        return self.ui.alpha0.value()

    @alpha0.setter
    def alpha0(self, v: float) -> None:
        self.ui.alpha0.setValue(v)

    @property
    def alpha1(self) -> float:
        return self.ui.alpha1.value()

    @alpha1.setter
    def alpha1(self, v: float) -> None:
        self.ui.alpha1.setValue(v)

    @property
    def beta0(self) -> float:
        return self.ui.beta0.value()

    @beta0.setter
    def beta0(self, v: float) -> None:
        self.ui.beta0.setValue(v)

    @property
    def beta1(self) -> float:
        return self.ui.beta1.value()

    @beta1.setter
    def beta1(self, v: float) -> None:
        self.ui.beta1.setValue(v)


# If this gets added as a list to hexrd, we can import it from there
peak_types = [
    'gaussian',
    'pvoigt',
    'split_pvoigt',
    'pink_beam_dcs',
]

# If this gets added as a list to hexrd, we can import it from there
background_types = [
    'constant',
    'linear',
    'quadratic',
    'cubic',
    'quartic',
    'quintic',
]

peak_type_to_label_map = {
    'gaussian': 'Gaussian',
    'pvoigt': 'PVoigt',
    'split_pvoigt': 'SplPVoigt',
    'pink_beam_dcs': 'DCS',
}

background_type_to_label_map: dict[str, Any] = {}


def peak_type_to_label(t: str) -> str:
    return peak_type_to_label_map.get(t, t.capitalize())


def background_type_to_label(t: str) -> str:
    return background_type_to_label_map.get(t, t.capitalize())
