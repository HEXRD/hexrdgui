from functools import partial
import traceback

import numpy as np

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from hexrd.fitting.calibration import InstrumentCalibrator, PowderCalibrator

from hexrdgui.async_runner import AsyncRunner
from hexrdgui.calibration.auto import PowderCalibrationDialog
from hexrdgui.calibration.calibration_dialog import CalibrationDialog
from hexrdgui.calibration.material_calibration_dialog_callbacks import (
    format_material_params_func,
    MaterialCalibrationDialogCallbacks,
)
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils import masks_applied_to_panel_buffers
from hexrdgui.utils.guess_instrument_type import guess_instrument_type


class PowderRunner(QObject):

    calibration_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.parent = parent
        self.async_runner = AsyncRunner(parent)

    def clear(self):
        # Nothing to do right now...
        pass

    def run(self):
        try:
            self.validate()
            self._run()
        except Exception as e:
            QMessageBox.critical(self.parent, 'HEXRD', f'Error: {e}')
            traceback.print_exc()

    def validate(self):
        overlays = self.visible_powder_overlays
        if len(overlays) != 1:
            raise Exception('There must be exactly one visible powder overlay')

    def _run(self):
        # First, have the user pick some options
        if not PowderCalibrationDialog(self.material, self.parent).exec():
            # User canceled...
            return

        # The options they chose are saved here
        options = HexrdConfig().config['calibration']['powder']
        self.instr = create_hedm_instrument()
        # Set this for the default calibration flags we will use
        self.instr.calibration_flags = (
            HexrdConfig().get_statuses_instrument_format()
        )

        if options['auto_guess_initial_fwhm']:
            fwhm_estimate = None
        else:
            fwhm_estimate = options['initial_fwhm']

        engineering_constraints = guess_instrument_type(self.instr.detectors)

        # Get an intensity-corrected masked dict of the images
        img_dict = HexrdConfig().masked_images_dict

        kwargs = {
            'instr': self.instr,
            'material': self.material,
            'img_dict': img_dict,
            'default_refinements': self.active_overlay.refinements,
            'eta_tol': options['eta_tol'],
            'fwhm_estimate': fwhm_estimate,
            'pktype': options['pk_type'],
            'bgtype': options['bg_type'],
            'tth_distortion': self.active_overlay.tth_distortion_dict,
        }

        self.pc = PowderCalibrator(**kwargs)
        self.ic = InstrumentCalibrator(
            self.pc, engineering_constraints=engineering_constraints
        )
        self.extract_powder_lines()

    def extract_powder_lines(self):
        self.async_runner.progress_title = 'Auto picking points...'
        self.async_runner.success_callback = self.extract_powder_lines_finished
        self.async_runner.run(self.run_extract_powder_lines)

    def run_extract_powder_lines(self):
        options = HexrdConfig().config['calibration']['powder']
        kwargs = {
            'fit_tth_tol': options['fit_tth_tol'],
            'int_cutoff': options['int_cutoff'],
        }

        # Apply any masks to the panel buffer for our instrument.
        # This is done so that the auto picking will skip over masked regions.
        with masks_applied_to_panel_buffers(self.instr):
            # This will save the results on self.pc
            self.pc.autopick_points(**kwargs)

        # Save the picks to the active overlay in case we need them later
        self.save_picks_to_overlay()

    def extract_powder_lines_finished(self):
        self.show_calibration_dialog()

    def show_calibration_dialog(self):
        format_extra_params_func = partial(
            format_material_params_func,
            overlays=[self.active_overlay],
            calibrators=[self.pc],
        )

        # Now show the calibration dialog
        kwargs = {
            'instr': self.instr,
            'params_dict': self.ic.params,
            'format_extra_params_func': format_extra_params_func,
            'parent': self.parent,
            'engineering_constraints': self.ic.engineering_constraints,
            'window_title': 'Fast Powder Calibration',
            'help_url': 'calibration/fast_powder',
        }
        dialog = CalibrationDialog(**kwargs)

        # Connect interactions to functions
        self._dialog_callback_handler = CalibrationCallbacks(
            [self.active_overlay],
            dialog,
            self.ic,
            self.instr,
            self.async_runner,
        )
        self._dialog_callback_handler.instrument_updated.connect(
            self.on_calibration_finished)
        dialog.show()

        self._calibration_dialog = dialog

        return dialog

    def on_calibration_finished(self):
        material_modified = any(
            self.ic.params[param_name].vary
            for param_name in self.pc.param_names
        )

        if material_modified:
            # The material might have changed. Indicate that.
            mat_name = self.material.name
            HexrdConfig().flag_overlay_updates_for_material(mat_name)
            HexrdConfig().material_modified.emit(mat_name)
            HexrdConfig().overlay_config_changed.emit()

        self.calibration_finished.emit()

    @property
    def overlays(self):
        return HexrdConfig().overlays

    @property
    def visible_overlays(self):
        return [x for x in self.overlays if x.visible]

    @property
    def visible_powder_overlays(self):
        overlays = self.visible_overlays
        return [x for x in overlays if x.is_powder]

    @property
    def active_overlay(self):
        overlays = self.visible_powder_overlays
        return overlays[0] if overlays else None

    @property
    def material(self):
        overlay = self.active_overlay
        return overlay.material if overlay else None

    def save_picks_to_overlay(self):
        # Currently, we only have one active overlay
        self.active_overlay.calibration_picks = self.pc.calibration_picks


class CalibrationCallbacks(MaterialCalibrationDialogCallbacks):

    @property
    def data_xys(self):
        ret = {}
        for k, v in self.overlays[0].calibration_picks.items():
            points = list(v.values())
            if not points:
                # No points on this detector
                ret[k] = []
                continue

            ret[k] = np.vstack(points)
        return ret

    def draw_picks_on_canvas(self):
        HexrdConfig().auto_picked_data = self.data_xys

    def clear_drawn_picks(self):
        HexrdConfig().auto_picked_data = None

    def on_edit_picks_clicked(self):
        dialog = self.create_hkl_picks_tree_view_dialog()
        dialog.button_box_visible = True
        dialog.ui.show()

        def on_finished():
            self.dialog.show()
            self.redraw_picks()

        dialog.ui.accepted.connect(self.on_edit_picks_accepted)
        dialog.ui.finished.connect(on_finished)

        self.edit_picks_dialog = dialog

        self.clear_drawn_picks()
        self.dialog.hide()

    def save_picks_to_file(self, selected_file):
        # Reuse the same logic from the HKLPicksTreeViewDialog
        dialog = self.create_hkl_picks_tree_view_dialog()
        dialog.export_picks(selected_file)

    def load_picks_from_file(self, selected_file):
        # Reuse the same logic from the HKLPicksTreeViewDialog
        dialog = self.create_hkl_picks_tree_view_dialog()
        dialog.import_picks(selected_file)
        return dialog.dictionary
