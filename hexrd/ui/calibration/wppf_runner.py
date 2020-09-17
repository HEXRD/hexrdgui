import numpy as np

from PySide2.QtCore import QObject, QThreadPool, Signal

from hexrd.material import _angstroms
from hexrd.WPPF import LeBail, Rietveld

from hexrd.ui.calibration.wppf_options_dialog import WppfOptionsDialog
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.progress_dialog import ProgressDialog


class WppfRunner(QObject):

    progress_text = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.thread_pool = QThreadPool(self)
        self.progress_dialog = ProgressDialog(parent)
        self.progress_text.connect(self.progress_dialog.setLabelText)

    def clear(self):
        self.wppf_options_dialog = None

    def run(self):
        # We will go through these steps:
        # 1. Select options
        # 2. Run WPPF
        self.select_options()

    def select_options(self):
        dialog = WppfOptionsDialog(self.parent())
        dialog.accepted.connect(self.wppf_options_selected)
        dialog.rejected.connect(self.clear)
        dialog.show()
        self.wppf_options_dialog = dialog

    def wppf_options_selected(self):
        # FIXME: run this in a background thread (code for this is
        # commented out below). The reason we can't do it right now
        # is because the spline background method pops up a dialog
        # with pylab, and we can't interact with it if it is running
        # in a background thread. If that gets changed, we can run
        # this in a background thread.
        self.run_wppf()
        self.wppf_finished()

        # Run WPPF in a background thread
        # self.progress_dialog.setWindowTitle('Running WPPF')
        # self.progress_dialog.setRange(0, 0)  # no numerical updates

        # worker = AsyncWorker(self.run_wppf)
        # self.thread_pool.start(worker)

        # worker.signals.result.connect(self.wppf_finished)
        # worker.signals.finished.connect(self.progress_dialog.accept)
        # self.progress_dialog.exec_()

    def run_wppf(self):
        dialog = self.wppf_options_dialog
        method = dialog.wppf_method

        if method == 'LeBail':
            class_type = LeBail
        elif method == 'Rietveld':
            class_type = Rietveld
        else:
            raise Exception(f'Unknown method: {method}')

        wavelength = {
            'synchrotron': _angstroms(HexrdConfig().beam_wavelength)
        }

        if dialog.use_experiment_file:
            expt_spectrum = np.loadtxt(dialog.experiment_file)
        else:
            expt_spectrum = HexrdConfig().last_azimuthal_integral_data
            # Re-format it to match the expected input format
            expt_spectrum = np.array(list(zip(*expt_spectrum)))

        kwargs = {
            'expt_spectrum': expt_spectrum,
            'params': dialog.params,
            'phases': HexrdConfig().active_material,
            'wavelength': wavelength,
            'bkgmethod': dialog.background_method_dict
        }

        self.wppf_object = class_type(**kwargs)

        for i in range(dialog.refinement_steps):
            self.wppf_object.RefineCycle()

    def wppf_finished(self):
        HexrdConfig().wppf_data = list(self.wppf_object.spectrum_sim.data)
        HexrdConfig().rerender_needed.emit()

    def update_progress_text(self, text):
        self.progress_text.emit(text)
