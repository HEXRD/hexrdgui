from PySide2.QtWidgets import QMessageBox

import numpy as np

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class LaueAutoPickerDialog:

    def __init__(self, overlay, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('laue_auto_picker_dialog.ui', parent)

        self.overlay = overlay
        self.overlay_modified = False

        self.update_gui()

    def update_gui(self):
        if self.tth_tol is None or self.eta_tol is None:
            options = HexrdConfig().config['calibration']['laue_auto_picker']
            tth_tol = options['tth_tol']
            eta_tol = options['eta_tol']
            msg = (
                'Laue widths are required.\n\n'
                f'Setting to defaults: {tth_tol}° (tth) and {eta_tol}° (eta)'
            )
            QMessageBox.warning(self.ui.parent(), 'HEXRD', msg)
            self.tth_tol = tth_tol
            self.eta_tol = eta_tol

        self.ui.tth_tol.setValue(self.tth_tol)
        self.ui.eta_tol.setValue(self.eta_tol)

        options = HexrdConfig().config['calibration']['laue_auto_picker']
        self.ui.npdiv.setValue(options['npdiv'])
        self.ui.fit_peaks.setChecked(options['fit_peaks'])
        self.ui.fit_tth_tol.setValue(options['fit_tth_tol'])
        self.ui.min_peak_int.setValue(options['min_peak_int'])
        self.ui.do_smoothing.setChecked(options['do_smoothing'])
        self.ui.smoothing_sigma.setValue(options['smoothing_sigma'])
        self.ui.use_blob_detection.setChecked(options['use_blob_detection'])
        self.ui.blob_threshold.setValue(options['blob_threshold'])

    def update_config(self):
        self.tth_tol = self.ui.tth_tol.value()
        self.eta_tol = self.ui.eta_tol.value()

        options = HexrdConfig().config['calibration']['laue_auto_picker']
        options['npdiv'] = self.ui.npdiv.value()
        options['fit_peaks'] = self.ui.fit_peaks.isChecked()
        options['fit_tth_tol'] = self.ui.fit_tth_tol.value()
        options['min_peak_int'] = self.ui.min_peak_int.value()
        options['do_smoothing'] = self.ui.do_smoothing.isChecked()
        options['smoothing_sigma'] = self.ui.smoothing_sigma.value()
        options['use_blob_detection'] = self.ui.use_blob_detection.isChecked()
        options['blob_threshold'] = self.ui.blob_threshold.value()

    def exec_(self):
        if not self.ui.exec_():
            return False

        self.update_config()

        if self.overlay_modified:
            material = self.overlay.material_name
            HexrdConfig().material_tth_width_modified.emit(material)
            HexrdConfig().flag_overlay_updates_for_material(material)

        return True

    @property
    def tth_tol(self):
        return np.degrees(self.overlay.tth_width)

    @tth_tol.setter
    def tth_tol(self, v):
        self.overlay.tth_width = np.radians(v)
        self.overlay_modified = True

    @property
    def eta_tol(self):
        return np.degrees(self.overlay.eta_width)

    @eta_tol.setter
    def eta_tol(self, v):
        self.overlay.eta_width = np.radians(v)
        self.overlay_modified = True
