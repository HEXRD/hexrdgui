from hexrd.fitting.calibration.lmfit_param_handling import normalize_euler_convention

from hexrdgui.calibration.calibration_dialog import TILT_LABELS_EULER
from hexrdgui.calibration.calibration_dialog_callbacks import (
    CalibrationDialogCallbacks,
)
from hexrdgui.calibration.hkl_picks_tree_view_dialog import (
    overlays_to_tree_format,
    HKLPicksTreeViewDialog,
)
from hexrdgui.constants import ViewType
from hexrdgui.hexrd_config import HexrdConfig


class MaterialCalibrationDialogCallbacks(CalibrationDialogCallbacks):

    def __init__(self, overlays, dialog, calibrator, instr, async_runner):
        self.overlays = overlays

        if not hasattr(self, 'edit_picks_dialog'):
            self.edit_picks_dialog = None

        super().__init__(dialog, calibrator, instr, async_runner)

    @property
    def calibrators(self):
        return self.calibrator.calibrators

    def create_hkl_picks_tree_view_dialog(self):
        kwargs = {
            'dictionary': overlays_to_tree_format(self.overlays),
            'coords_type': ViewType.polar,
            'canvas': self.canvas,
            'parent': self.canvas,
        }
        return HKLPicksTreeViewDialog(**kwargs)

    def update_edit_picks_dictionary(self):
        if self.edit_picks_dialog is None:
            # Nothing to update
            return

        tree_format = overlays_to_tree_format(self.overlays)
        self.edit_picks_dialog.dictionary = tree_format

    @property
    def edit_picks_dictionary(self):
        if self.edit_picks_dialog is None:
            return {}

        return self.edit_picks_dialog.dictionary

    def set_picks(self, picks):
        self.validate_picks(picks)

        overlays = {x.name: x for x in self.overlays}
        for name, overlay_picks in picks.items():
            overlays[name].calibration_picks_polar = overlay_picks

        # Update the data on the calibrators
        for calibrator, overlay in zip(self.calibrators, self.overlays):
            calibrator.calibration_picks = overlay.calibration_picks

        self.update_edit_picks_dictionary()

        # Update the dialog
        self.redraw_picks()

    def on_edit_picks_accepted(self):
        # Write the modified picks to the overlays
        self.set_picks(self.edit_picks_dictionary)

    def on_calibration_finished(self):
        super().on_calibration_finished()

        # Now make sure the overlays have updated instruments
        for overlay in self.overlays:
            overlay.instrument = self.instr

    def validate_picks(self, picks):
        if len(picks) != len(self.overlays):
            msg = (
                f'Number of picks ({len(picks)}) do not match number of '
                f'overlays ({len(picks)}).'
            )
            raise Exception(msg)

        instr_dets = sorted(list(self.instr.detectors))

        overlay_names = [x.name for x in self.overlays]
        for name, overlay_picks in picks.items():
            if name not in overlay_names:
                msg = (
                    f'Picks names ({list(picks)}) do not match overlay names '
                    f'({overlay_names})'
                )
                raise Exception(msg)

            det_keys = sorted(list(overlay_picks))
            if det_keys != instr_dets:
                msg = (
                    f'Detector keys ({det_keys}) for picks "{name}" do not '
                    f'match instrument keys ({instr_dets})'
                )
                raise Exception(msg)


def format_material_params_func(
    params_dict, tree_dict, create_param_item, overlays, calibrators
):
    tree_dict.setdefault('Materials', {})
    for overlay, calibrator in zip(overlays, calibrators):
        if not calibrator.param_names:
            continue

        d = tree_dict['Materials'].setdefault(overlay.name, {})
        if calibrator.type == 'powder':
            for name in calibrator.param_names:
                # Assume this for now...
                lat_param_name = name.split('_')[-1]
                d[lat_param_name] = create_param_item(params_dict[name])
        else:
            # Assume grain parameters
            d['Orientation'] = {}
            euler_convention = normalize_euler_convention(
                HexrdConfig().euler_angle_convention
            )
            labels = TILT_LABELS_EULER[euler_convention]
            for i in range(3):
                param = params_dict[calibrator.param_names[i]]
                d['Orientation'][labels[i]] = create_param_item(param)

            d['Position'] = {}
            labels = ['X', 'Y', 'Z']
            for i in range(3):
                param = params_dict[calibrator.param_names[i + 3]]
                d['Position'][labels[i]] = create_param_item(param)

            d['Stretch'] = {}
            labels = ['U_xx', 'U_yy', 'U_zz', 'U_yz', 'U_xz', 'U_xy']
            for i in range(6):
                param = params_dict[calibrator.param_names[i + 6]]
                d['Stretch'][labels[i]] = create_param_item(param)
