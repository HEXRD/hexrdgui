import copy

from PySide2.QtCore import QCoreApplication, QObject, QThreadPool, Signal

from hexrd.ui.calibration.wppf_options_dialog import WppfOptionsDialog
from hexrd.ui.constants import OverlayType
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
        self.validate()

        # We will go through these steps:
        # 1. Select options
        # 2. Run WPPF
        self.select_options()

    def validate(self):
        if not self.visible_powder_overlays:
            raise Exception('At least one visible powder overlay is required')

    @property
    def visible_powder_overlays(self):
        return [
            x for x in HexrdConfig().overlays
            if (x['type'] == OverlayType.powder and x['visible'])
        ]

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
        self.wppf_object = dialog.create_wppf_object()

        for i in range(dialog.refinement_steps):
            self.wppf_object.RefineCycle()
            self.rerender_wppf()

        self.write_lattice_params_to_materials()

    def rerender_wppf(self):
        HexrdConfig().wppf_data = list(self.wppf_object.spectrum_sim.data)
        HexrdConfig().rerender_wppf.emit()

        # Process events to make sure it visually updates.
        # If this causes issues, we can post self.wppf_object.RefineCycle()
        # calls to the event loop in the future instead.
        QCoreApplication.processEvents()

    def wppf_finished(self):
        self.update_param_values()

    def write_lattice_params_to_materials(self):
        for name, wppf_mat in self.wppf_object.phases.phase_dict.items():
            mat = HexrdConfig().material(name)

            # Convert units from nm to angstroms
            lparms = copy.deepcopy(wppf_mat.lparms)
            for i in range(3):
                lparms[i] *= 10.0

            mat.latticeParameters = lparms
            HexrdConfig().flag_overlay_updates_for_material(name)

            if mat is HexrdConfig().active_material:
                HexrdConfig().active_material_modified.emit()

        HexrdConfig().overlay_config_changed.emit()

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
