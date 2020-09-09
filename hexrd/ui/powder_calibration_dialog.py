from hexrd.ui import enter_key_filter

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class PowderCalibrationDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('powder_calibration_dialog.ui', parent)
        self.ui.installEventFilter(enter_key_filter)

        self.update_gui_from_config()
        self.setup_connections()

    def setup_connections(self):
        pass

    def update_gui_from_config(self):
        tth_tol = HexrdConfig().config['calibration']['powder']['tth_tol']
        eta_tol = HexrdConfig().config['calibration']['powder']['eta_tol']
        pk_type = HexrdConfig().config['calibration']['powder']['pk_type']

        if pk_type == 'pvoigt':
            pk_type = 'PVoigt'
        elif pk_type == 'gaussian':
            pk_type = 'Gaussian'

        self.ui.tth_tolerance.setValue(tth_tol)
        self.ui.eta_tolerance.setValue(eta_tol)
        self.ui.peak_fit_type.setCurrentText(pk_type)

    def exec_(self):
        if not self.ui.exec_():
            return False

        tth_tol = self.ui.tth_tolerance.value()
        eta_tol = self.ui.eta_tolerance.value()
        pk_type = self.ui.peak_fit_type.currentText().lower()

        HexrdConfig().config['calibration']['powder']['tth_tol'] = tth_tol
        HexrdConfig().config['calibration']['powder']['eta_tol'] = eta_tol
        HexrdConfig().config['calibration']['powder']['pk_type'] = pk_type
        return True
