from __future__ import annotations

from typing import Any, TYPE_CHECKING

from PySide6.QtWidgets import QDoubleSpinBox, QLabel, QMessageBox, QWidget

import numpy as np

from hexrd.core.fitting.spectrum import pink_beam_asymmetry_params

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader

if TYPE_CHECKING:
    from hexrd.material import Material

# Number of generic (label, spinbox) rows in the asymmetry group in the .ui.
# Must be at least as large as the biggest set in pink_beam_asymmetry_params.
NUM_ASYMMETRY_ROWS = 4

# Pretty labels for each shape parameter shown in the dialog.
ASYMMETRY_PARAM_LABELS = {
    'alpha0': 'α₀',
    'alpha1': 'α₁',
    'beta0': 'β₀',
    'beta1': 'β₁',
    'sigma0': 'σ₀',
    'sigma1': 'σ₁',
    'tau0': 'τ₀',
    'tau1': 'τ₁',
    'tau2': 'τ₂',
}

# Sensible defaults (matching the hexrd/WPPF defaults for each profile), used
# when a config has no value yet and the user never populates from WPPF.
ASYMMETRY_PARAM_DEFAULTS = {
    'alpha0': 14.4,
    'alpha1': 0.0,
    'beta0': 3.016,
    'beta1': -7.94,
    'sigma0': 0.1,
    'sigma1': 0.1,
    'tau0': 1.58,
    'tau1': -1.35,
    'tau2': 0.36,
}


class PowderCalibrationDialog:
    def __init__(self, material: Material, parent: QWidget | None = None) -> None:
        loader = UiLoader()
        self.ui = loader.load_file('powder_calibration_dialog.ui', parent)

        self.material = material

        # All shape-parameter values, keyed by name. The visible spinboxes
        # show whichever subset matches the selected pink-beam peak type;
        # `_shown_params` tracks which params those spinboxes currently hold.
        self._asymmetry_values = dict(ASYMMETRY_PARAM_DEFAULTS)
        self._shown_params: list[str] = []

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
        # Re-sync the asymmetry fields when the peak fit type changes or the
        # group is toggled (the inputs are hidden entirely while unchecked).
        self.ui.peak_fit_type.currentIndexChanged.connect(self.sync_asymmetry_fields)
        self.ui.use_wppf_asymmetry_check.toggled.connect(self.sync_asymmetry_fields)
        self.ui.populate_from_wppf_button.clicked.connect(
            self.populate_asymmetry_from_wppf
        )

    def asym_label(self, i: int) -> QLabel:
        return getattr(self.ui, f'asym_label_{i}')

    def asym_value(self, i: int) -> QDoubleSpinBox:
        return getattr(self.ui, f'asym_value_{i}')

    @property
    def asymmetry_params(self) -> tuple[str, ...]:
        # The shape params for the selected pink-beam type (empty otherwise).
        return pink_beam_asymmetry_params.get(self.peak_fit_type, ())

    def capture_shown_asymmetry_values(self) -> None:
        # Preserve any edits in the spinboxes (which retain their values even
        # while hidden) before they get repopulated for a different peak type.
        for i, name in enumerate(self._shown_params):
            self._asymmetry_values[name] = self.asym_value(i).value()

    def render_asymmetry_fields(self) -> None:
        params = self.asymmetry_params
        # The whole section only makes sense for the pink-beam profiles.
        self.ui.asymmetry_container.setVisible(bool(params))

        # Hide the inputs entirely (not just disable them) while the option is
        # off - they are only needed in rare cases and otherwise waste space.
        checked = self.use_wppf_asymmetry
        self.ui.populate_from_wppf_button.setVisible(checked)
        for i in range(NUM_ASYMMETRY_ROWS):
            label = self.asym_label(i)
            spinbox = self.asym_value(i)
            applies = i < len(params)
            if applies:
                name = params[i]
                label.setText(f'{ASYMMETRY_PARAM_LABELS[name]}:')
                spinbox.setValue(self._asymmetry_values[name])
            label.setVisible(checked and applies)
            spinbox.setVisible(checked and applies)

        self._shown_params = list(params)

    def sync_asymmetry_fields(self) -> None:
        self.capture_shown_asymmetry_values()
        self.render_asymmetry_fields()

    def populate_asymmetry_from_wppf(self) -> None:
        params = self.asymmetry_params
        wppf_params = (
            HexrdConfig()
            .config.get('calibration', {})
            .get('wppf', {})
            .get('params_dict', {})
        )
        missing = [k for k in params if k not in wppf_params]
        if not params or missing:
            QMessageBox.warning(
                self.ui,
                'HEXRD',
                'Could not find pink-beam asymmetry parameters from a '
                'previous WPPF run. Missing: ' + ', '.join(missing) + '.\n\n'
                'Run a WPPF refinement with the matching pink-beam peak '
                'shape first.',
            )
            return

        for name in params:
            self._asymmetry_values[name] = float(wppf_params[name]['value'])
        self.render_asymmetry_fields()

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

        # Asymmetry group (may not exist in older configs). Load all known
        # shape values (with `_shown_params` empty) before touching the
        # checkbox or peak type, so the signals they fire don't capture stale
        # spinbox values over the values we just loaded.
        asym_cfg = options.get('fixed_pink_asymmetry') or {}
        self._asymmetry_values = {
            name: float(asym_cfg.get(name, default))
            for name, default in ASYMMETRY_PARAM_DEFAULTS.items()
        }
        self._shown_params = []
        self.use_wppf_asymmetry = bool(asym_cfg.get('enabled', False))

        self.peak_fit_type = options['pk_type']
        self.background_type = options['bg_type']

        # Render the fields for the current peak type (also sets visibility).
        self.render_asymmetry_fields()

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

        # Capture any edits currently in the visible spinboxes, then persist
        # the full set of shape values (all peak types) plus the toggle.
        self.capture_shown_asymmetry_values()
        options['fixed_pink_asymmetry'] = {
            'enabled': self.use_wppf_asymmetry,
            **self._asymmetry_values,
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
        return self.ui.use_wppf_asymmetry_check.isChecked()

    @use_wppf_asymmetry.setter
    def use_wppf_asymmetry(self, b: bool) -> None:
        self.ui.use_wppf_asymmetry_check.setChecked(b)


# If this gets added as a list to hexrd, we can import it from there
peak_types = [
    'gaussian',
    'pvoigt',
    'split_pvoigt',
    'pink_beam_dcs',
    'pink_beam_heating',
    'pink_beam_exponential',
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
    'pink_beam_heating': 'Pink Heating',
    'pink_beam_exponential': 'Pink Exp',
}

background_type_to_label_map: dict[str, Any] = {}


def peak_type_to_label(t: str) -> str:
    return peak_type_to_label_map.get(t, t.capitalize())


def background_type_to_label(t: str) -> str:
    return background_type_to_label_map.get(t, t.capitalize())
