import numpy as np

from PySide2.QtCore import QCoreApplication, QObject, QThreadPool, Signal

from hexrd.material import _angstroms
from hexrd.WPPF import LeBail, Rietveld

from hexrd.ui.calibration.wppf_options_dialog import WppfOptionsDialog
from hexrd.ui.constants import OverlayType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.progress_dialog import ProgressDialog


class WppfRunner(QObject):

    progress_text = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._spec_offset = 0
        self.thread_pool = QThreadPool(self)
        self.progress_dialog = ProgressDialog(parent)
        self.progress_text.connect(self.progress_dialog.setLabelText)

    def clear(self):
        self.wppf_options_dialog = None

    def run(self):
        self.validate()

        # We will go through these steps:
        # 1. Select options
        # 2. Run WPPF
        self.select_options()

    def validate(self):
        powder_overlays = [
            x for x in HexrdConfig().overlays
            if (x['type'] == OverlayType.powder and x['visible'])
        ]
        if not powder_overlays:
            raise Exception('At least one visible powder overlay is required')

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

        # Add offset to ensure we pass WPPF values greater than zero
        min_value = expt_spectrum[:, 1].min()
        max_value = expt_spectrum[:, 1].max()
        # Generate the offset -min value + 0.5% of max value
        self._spec_offset = -min_value + max_value * 0.005
        expt_spectrum[:, 1] = np.add(expt_spectrum[:, 1], self._spec_offset)

        phases = [HexrdConfig().material(x) for x in dialog.selected_materials]
        kwargs = {
            'expt_spectrum': expt_spectrum,
            'params': dialog.params,
            'phases': phases,
            'wavelength': wavelength,
            'bkgmethod': dialog.background_method_dict
        }

        self.wppf_object = class_type(**kwargs)

        for i in range(dialog.refinement_steps):
            self.wppf_object.RefineCycle()
            self.rerender_wppf()

    def rerender_wppf(self):
        # We need to remove the offset before rendering
        (x, y) = self.wppf_object.spectrum_sim.data
        y = np.add(np.copy(y), -self._spec_offset)
        HexrdConfig().wppf_data = (x, y)

        HexrdConfig().rerender_wppf.emit()

        # Process events to make sure it visually updates.
        # If this causes issues, we can post self.wppf_object.RefineCycle()
        # calls to the event loop in the future instead.
        QCoreApplication.processEvents()

    def wppf_finished(self):
        self.update_param_values()

    def update_param_values(self):
        # Update the param values with their new values from the wppf_object
        params = self.params
        if not params:
            return

        new_params = self.wppf_object.params
        for k, v in params.items():
            v[0] = new_params[k].value

    @property
    def params(self):
        conf = HexrdConfig().config['calibration']
        return conf.get('wppf', {}).get('params')

    def update_progress_text(self, text):
        self.progress_text.emit(text)
