import copy

from PySide2.QtCore import QCoreApplication

from hexrd.wppf import Rietveld

from hexrd.ui.calibration.wppf_options_dialog import WppfOptionsDialog
from hexrd.ui.hexrd_config import HexrdConfig


class WppfRunner:

    def __init__(self, parent=None):
        self.parent = parent

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
        return [x for x in HexrdConfig().overlays if x.is_powder and x.visible]

    def select_options(self):
        dialog = WppfOptionsDialog(self.parent)
        dialog.run.connect(self.run_wppf)
        dialog.finished.connect(self.clear)
        dialog.show()
        self.wppf_options_dialog = dialog

    def run_wppf(self):
        dialog = self.wppf_options_dialog
        self.wppf_object = dialog.wppf_object

        # Work around differences in WPPF objects
        if isinstance(self.wppf_object, Rietveld):
            refine_func = self.wppf_object.Refine
        else:
            refine_func = self.wppf_object.RefineCycle

        for i in range(dialog.refinement_steps):
            refine_func()
            self.rerender_wppf()

        self.write_lattice_params_to_materials()
        self.update_param_values()

    def rerender_wppf(self):
        HexrdConfig().wppf_data = list(self.wppf_object.spectrum_sim.data)
        HexrdConfig().rerender_wppf.emit()

        # Process events to make sure it visually updates.
        # If this causes issues, we can post self.wppf_object.RefineCycle()
        # calls to the event loop in the future instead.
        QCoreApplication.processEvents()

    def write_lattice_params_to_materials(self):
        for name, wppf_mat in self.wppf_object.phases.phase_dict.items():
            mat = HexrdConfig().material(name)

            # Work around differences in WPPF objects
            if isinstance(self.wppf_object, Rietveld):
                lparms = wppf_mat['synchrotron'].lparms
            else:
                lparms = wppf_mat.lparms

            # Convert units from nm to angstroms
            lparms = copy.deepcopy(lparms)
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

        new_params = self.wppf_object.params
        for k, v in params.items():
            v['value'] = new_params[k].value

        dialog = self.wppf_options_dialog
        dialog.load_settings()
        dialog.update_gui()

    @property
    def params(self):
        conf = HexrdConfig().config['calibration']
        return conf.setdefault('wppf', {}).setdefault('params_dict', {})
