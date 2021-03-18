from hexrd.ui import enter_key_filter

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class PowderCalibrationDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('powder_calibration_dialog.ui', parent)
        self.ui.installEventFilter(enter_key_filter)

        self.update_gui()

    def update_gui(self):
        options = HexrdConfig().config['calibration']['powder']
        tth_tol = options['tth_tol']
        eta_tol = options['eta_tol']
        pk_type = options['pk_type']
        robust = options['use_robust_optimization']

        if pk_type == 'pvoigt':
            pk_type = 'PVoigt'
        elif pk_type == 'gaussian':
            pk_type = 'Gaussian'

        self.ui.tth_tolerance.setValue(tth_tol)
        self.ui.eta_tolerance.setValue(eta_tol)
        self.ui.peak_fit_type.setCurrentText(pk_type)
        self.ui.robust.setChecked(robust)

    def update_config(self):
        tth_tol = self.ui.tth_tolerance.value()
        eta_tol = self.ui.eta_tolerance.value()
        pk_type = self.ui.peak_fit_type.currentText().lower()
        robust = self.ui.robust.isChecked()

        options = HexrdConfig().config['calibration']['powder']
        options['tth_tol'] = tth_tol
        options['eta_tol'] = eta_tol
        options['pk_type'] = pk_type
        options['use_robust_optimization'] = robust

    def exec_(self):
        if not self.ui.exec_():
            return False

        self.update_config()
        return True
