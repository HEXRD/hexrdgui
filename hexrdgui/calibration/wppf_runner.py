import copy

from PySide6.QtCore import QCoreApplication

from hexrd.material import Material
from hexrd.wppf import Rietveld

from hexrdgui.calibration.wppf_options_dialog import WppfOptionsDialog
from hexrdgui.hexrd_config import HexrdConfig


class WppfRunner:

    def __init__(self, parent=None):
        self.parent = parent
        self.undo_stack = []

    def clear(self):
        self.wppf_options_dialog = None
        self.undo_stack.clear()

        self.clear_wppf_plots()
        HexrdConfig().show_wppf_difference_axis = False

    def clear_wppf_plots(self):
        HexrdConfig().wppf_data = None
        HexrdConfig().wppf_background_lineout = None
        HexrdConfig().wppf_amorphous_lineout = None

        HexrdConfig().rerender_wppf.emit()

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
        dialog.undo_clicked.connect(self.pop_undo_stack)
        dialog.object_reset.connect(self.on_object_reset)
        dialog.finished.connect(self.clear)
        dialog.show()
        self.wppf_options_dialog = dialog

    def run_wppf(self):
        dialog = self.wppf_options_dialog
        self.wppf_object = dialog.wppf_object
        varying_texture = dialog.varying_texture_params

        if varying_texture:
            # Ensure texture data is set on the WPPF object.
            # This might be time-consuming.
            dialog.ensure_texture_data()
        else:
            # If there are any non-texture refinements, we ought
            # to clear the texture data.
            dialog.clear_texture_data()

        # Work around differences in WPPF objects
        if isinstance(self.wppf_object, Rietveld):
            if varying_texture:
                refine_func = self.wppf_object.RefineTexture
            else:
                refine_func = self.wppf_object.Refine
        else:
            refine_func = self.wppf_object.RefineCycle

        for i in range(dialog.refinement_steps):
            refine_func()
            self.rerender_wppf()

        if varying_texture:
            # Update the simulated spectrum (if needed)
            dialog.on_texture_params_modified()

        self.push_undo_stack()
        self.write_params_to_materials()
        self.update_param_values()

    def rerender_wppf(self):
        self.clear_wppf_plots()
        obj = self.wppf_object
        if obj is None:
            return

        HexrdConfig().wppf_data = list(obj.spectrum_sim.data)

        background = []
        if obj.background:
            background = list(obj.background.data)

        HexrdConfig().wppf_background_lineout = background

        amorphous_lineout = []
        if obj.amorphous_model is not None:
            tth_list = obj.amorphous_model.tth_list
            intensity = obj.amorphous_model.amorphous_lineout
            if len(background) > 1:
                # background[1] is the background intensity.
                # We will automatically add the background, if present.
                intensity += background[1]

            amorphous_lineout = [
                tth_list,
                intensity,
            ]

        HexrdConfig().wppf_amorphous_lineout = amorphous_lineout

        HexrdConfig().rerender_wppf.emit()

        # Process events to make sure it visually updates.
        # If this causes issues, we can post self.wppf_object.RefineCycle()
        # calls to the event loop in the future instead.
        QCoreApplication.processEvents()

    def write_params_to_materials(self):
        for name, wppf_mat in self.wppf_object.phases.phase_dict.items():
            mat = _material_for_name(name)

            # Work around differences in WPPF objects
            if isinstance(self.wppf_object, Rietveld):
                wppf_mat = wppf_mat['synchrotron']

            lparms = wppf_mat.lparms

            # Convert units from nm to angstroms
            lparms = copy.deepcopy(lparms)
            for i in range(3):
                lparms[i] *= 10.0

            mat.latticeParameters = lparms

            if isinstance(self.wppf_object, Rietveld):
                # Only update atom info and U if it is Rietveld
                mat.atominfo[:] = wppf_mat.atom_pos
                mat.U[:] = wppf_mat.U

            HexrdConfig().flag_overlay_updates_for_material(name)
            HexrdConfig().material_modified.emit(name)

        HexrdConfig().overlay_config_changed.emit()

    def push_undo_stack(self):
        # Save the previous material parameters
        mat_params = {}
        for name in self.wppf_object.phases.phase_dict:
            mat = _material_for_name(name)
            mat_params[name] = {
                'lparms': mat.lparms,
                'atominfo': mat.atominfo,
                'U': mat.U,
            }

        # Make a deep copy of all parameters
        self.undo_stack.append(copy.deepcopy(mat_params))

    def pop_undo_stack(self):
        entry = self.undo_stack.pop()

        for name, mat_params in entry.items():
            mat = _material_for_name(name)

            mat.lparms = mat_params['lparms']
            mat.atominfo[:] = mat_params['atominfo']
            mat.U[:] = mat_params['U']

            HexrdConfig().flag_overlay_updates_for_material(name)
            HexrdConfig().material_modified.emit(name)

        HexrdConfig().overlay_config_changed.emit()

        dialog = self.wppf_options_dialog
        # Use underscore method so we don't accidentally auto-create one
        self.wppf_object = dialog._wppf_object

        self.rerender_wppf()

    def on_object_reset(self):
        # Clear the WPPF plots
        self.clear_wppf_plots()

    def update_param_values(self):
        # Update the param values with their new values from the wppf_object
        params = self.params

        new_params = self.wppf_object.params
        for k, v in params.items():
            v['value'] = new_params[k].value

        dialog = self.wppf_options_dialog
        dialog.update_gui()

    @property
    def params(self):
        conf = HexrdConfig().config['calibration']
        return conf.setdefault('wppf', {}).setdefault('params_dict', {})


def _material_for_name(name: str) -> Material | None:
    # Find the matching name
    for internal_name in HexrdConfig().materials:
        if internal_name.replace('-', '_') == name:
            return HexrdConfig().material(internal_name)
