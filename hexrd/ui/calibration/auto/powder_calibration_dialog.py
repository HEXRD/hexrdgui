import numpy as np

from hexrd.ui import enter_key_filter

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class PowderCalibrationDialog:

    def __init__(self, material, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('powder_calibration_dialog.ui', parent)
        self.ui.installEventFilter(enter_key_filter)

        self.material = material

        self.update_gui()

    def update_gui(self):
        options = HexrdConfig().config['calibration']['powder']
        pk_type = options['pk_type']

        reformat = {
            'pvoigt': 'PVoigt',
            'gaussian': 'Gaussian',
        }
        self.ui.tth_tolerance.setValue(self.tth_tol)
        self.ui.eta_tolerance.setValue(options['eta_tol'])
        self.ui.fit_tth_tol.setValue(options['fit_tth_tol'])
        self.ui.max_iter.setValue(options['max_iter'])
        self.ui.int_cutoff.setValue(options['int_cutoff'])
        self.ui.conv_tol.setValue(options['conv_tol'])
        self.ui.peak_fit_type.setCurrentText(reformat.get(pk_type, pk_type))
        self.ui.robust.setChecked(options['use_robust_optimization'])

    def update_config(self):
        options = HexrdConfig().config['calibration']['powder']
        self.tth_tol = self.ui.tth_tolerance.value()
        options['eta_tol'] = self.ui.eta_tolerance.value()
        options['fit_tth_tol'] = self.ui.fit_tth_tol.value()
        options['max_iter'] = self.ui.max_iter.value()
        options['int_cutoff'] = self.ui.int_cutoff.value()
        options['conv_tol'] = self.ui.conv_tol.value()
        options['pk_type'] = self.ui.peak_fit_type.currentText().lower()
        options['use_robust_optimization'] = self.ui.robust.isChecked()

    def exec_(self):
        if not self.ui.exec_():
            return False

        self.update_config()
        return True

    @property
    def tth_tol(self):
        return np.degrees(self.material.planeData.tThWidth)

    @tth_tol.setter
    def tth_tol(self, v):
        v = np.radians(v)
        if self.material.planeData.tThWidth == v:
            # Just return...
            return

        self.material.planeData.tThWidth = v
        HexrdConfig().material_tth_width_modified.emit(self.material.name)
        HexrdConfig().flag_overlay_updates_for_material(self.material.name)
        HexrdConfig().overlay_config_changed.emit()
