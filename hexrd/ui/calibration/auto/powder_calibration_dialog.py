from PySide2.QtCore import QTimer
from PySide2.QtWidgets import QMessageBox

import numpy as np

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class PowderCalibrationDialog:

    def __init__(self, material, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('powder_calibration_dialog.ui', parent)

        self.material = material

        self.setup_combo_boxes()
        self.update_gui()

    def setup_combo_boxes(self):
        self.ui.peak_fit_type.clear()
        for t in peak_types:
            label = peak_type_to_label(t)
            self.ui.peak_fit_type.addItem(label, t)

        self.ui.background_type.clear()
        for t in background_types:
            label = background_type_to_label(t)
            self.ui.background_type.addItem(label, t)

    def update_gui(self):
        if self.tth_tol is None:
            default = 0.125
            msg = (
                'Powder overlay width is required.\n\n'
                f'Setting to default: {default}°'
            )
            QMessageBox.warning(self.ui.parent(), 'HEXRD', msg)
            self.tth_tol = default

        options = HexrdConfig().config['calibration']['powder']

        self.ui.tth_tolerance.setValue(self.tth_tol)
        self.ui.eta_tolerance.setValue(options['eta_tol'])
        self.ui.fit_tth_tol.setValue(options['fit_tth_tol'])
        self.ui.max_iter.setValue(options['max_iter'])
        self.ui.int_cutoff.setValue(options['int_cutoff'])
        self.ui.conv_tol.setValue(options['conv_tol'])
        self.ui.robust.setChecked(options['use_robust_optimization'])

        self.peak_fit_type = options['pk_type']
        self.background_type = options['bg_type']

    def update_config(self):
        options = HexrdConfig().config['calibration']['powder']
        self.tth_tol = self.ui.tth_tolerance.value()
        options['eta_tol'] = self.ui.eta_tolerance.value()
        options['fit_tth_tol'] = self.ui.fit_tth_tol.value()
        options['max_iter'] = self.ui.max_iter.value()
        options['int_cutoff'] = self.ui.int_cutoff.value()
        options['conv_tol'] = self.ui.conv_tol.value()
        options['use_robust_optimization'] = self.ui.robust.isChecked()

        options['pk_type'] = self.peak_fit_type
        options['bg_type'] = self.background_type

    def exec_(self):
        if not self.ui.exec_():
            return False

        self.update_config()
        return True

    @property
    def tth_tol(self):
        tth_width = self.material.planeData.tThWidth
        return None if tth_width is None else np.degrees(tth_width)

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

    @property
    def peak_fit_type(self):
        return self.ui.peak_fit_type.currentData()

    @peak_fit_type.setter
    def peak_fit_type(self, v):
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
    def background_type(self):
        return self.ui.background_type.currentData()

    @background_type.setter
    def background_type(self, v):
        w = self.ui.background_type
        found = False
        for i in range(w.count()):
            if w.itemData(i) == v:
                found = True
                w.setCurrentIndex(i)
                break

        if not found:
            raise Exception(f'Unknown background type: {v}')

    def show_optimization_parameters(self, b=True):
        self.ui.optimization_parameters_group.setVisible(b)

        # Resize later so that the dialog is the correct size
        QTimer.singleShot(0, lambda: self.ui.resize(self.ui.sizeHint()))


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

background_type_to_label_map = {}


def peak_type_to_label(t):
    return peak_type_to_label_map.get(t, t.capitalize())


def background_type_to_label(t):
    return background_type_to_label_map.get(t, t.capitalize())
