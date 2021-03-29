import traceback

import numpy as np

from PySide2.QtCore import QObject, Qt, Signal
from PySide2.QtWidgets import QCheckBox, QMessageBox

from hexrd.ui.async_runner import AsyncRunner
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.constants import OverlayType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import default_overlay_refinements
from hexrd.ui.utils import instr_to_internal_dict

from hexrd.ui.calibration.auto import (
    InstrumentCalibrator,
    PowderCalibrationDialog,
    PowderCalibrator,
)


class PowderRunner(QObject):

    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.parent = parent
        self.async_runner = AsyncRunner(parent)

    def clear(self):
        self.remove_lines()

        if hasattr(self, '_ask_if_lines_are_acceptable_box'):
            # Remove the box if it is still there...
            self._ask_if_lines_are_acceptable_box.reject()
            del self._ask_if_lines_are_acceptable_box

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

        if np.count_nonzero(self.refinement_flags) == 0:
            raise Exception('There are no refinable parameters')

    def _run(self):
        # First, have the user pick some options
        if not PowderCalibrationDialog(self.material, self.parent).exec_():
            # User canceled...
            return

        # The options they chose are saved here
        options = HexrdConfig().config['calibration']['powder']
        self.instr = create_hedm_instrument()

        # Assume there is only one image in each image series for now...
        img_dict = {k: x[0] for k, x in HexrdConfig().imageseries_dict.items()}

        statuses = self.refinement_flags_without_overlays
        self.cf = statuses
        self.instr.calibration_flags = statuses

        kwargs = {
            'instr': self.instr,
            'plane_data': self.material.planeData,
            'img_dict': img_dict,
            'flags': self.refinement_flags,
            'eta_tol': options['eta_tol'],
            'pktype': options['pk_type'],
        }

        self.pc = PowderCalibrator(**kwargs)
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
        self.data_dict = self.pc._extract_powder_lines(**kwargs)

    def extract_powder_lines_finished(self):
        try:
            self.draw_lines()
            self.ask_if_lines_are_acceptable()
        except Exception:
            self.remove_lines()
            raise

    @property
    def data_xys(self):
        return {k: np.vstack(v)[:, :2] for k, v in self.data_dict.items()}

    def show_lines(self, b):
        self.draw_lines() if b else self.remove_lines()

    def draw_lines(self):
        HexrdConfig().auto_picked_data = self.data_xys

    def remove_lines(self):
        HexrdConfig().auto_picked_data = None

    def ask_if_lines_are_acceptable(self):
        msg = 'Perform calibration with the points drawn?'
        box = QMessageBox(QMessageBox.Question, 'HEXRD', msg)
        standard_buttons = QMessageBox.StandardButton
        box.setStandardButtons(standard_buttons.Yes | standard_buttons.No)
        box.setWindowModality(Qt.NonModal)

        # Add a checkbox
        cb = QCheckBox('Show auto picks?')
        cb.setStyleSheet('margin-left:50%; margin-right:50%;')
        cb.setChecked(True)
        cb.toggled.connect(self.show_lines)

        box.setCheckBox(cb)
        box.show()

        box.finished.connect(self.remove_lines)
        box.accepted.connect(self.lines_accepted)

        self._show_auto_picks_check_box = cb
        self._ask_if_lines_are_acceptable_box = box

    def lines_accepted(self):
        # If accepted, run it
        self.async_runner.progress_title = 'Running calibration...'
        self.async_runner.success_callback = self.update_config
        self.async_runner.run(self.run_calibration)

    def run_calibration(self):
        options = HexrdConfig().config['calibration']['powder']

        ic = InstrumentCalibrator(self.pc)
        x0 = self.pc.instr.calibration_parameters[self.cf]
        kwargs = {
            'conv_tol': options['conv_tol'],
            'fit_tth_tol': options['fit_tth_tol'],
            'max_iter': options['max_iter'],
            'use_robust_optimization': options['use_robust_optimization'],
        }
        ic.run_calibration(**kwargs)
        x1 = self.pc.instr.calibration_parameters[self.cf]

        results_message = 'Calibration Results:\n'
        for params in np.vstack([x0, x1]).T:
            results_message += f'{params[0]:6.3e}--->{params[1]:6.3e}\n'

        print(results_message)

        self.results_message = results_message

    def update_config(self):
        msg = 'Optimization successful!'
        msg_box = QMessageBox(QMessageBox.Information, 'HEXRD', msg)
        msg_box.setDetailedText(self.results_message)
        msg_box.exec_()

        output_dict = instr_to_internal_dict(self.instr)

        # Save the previous iconfig to restore the statuses
        prev_iconfig = HexrdConfig().config['instrument']

        # Update the config
        HexrdConfig().config['instrument'] = output_dict

        # This adds in any missing keys. In particular, it is going to
        # add in any "None" detector distortions
        HexrdConfig().set_detector_defaults_if_missing()

        # Add status values
        HexrdConfig().add_status(output_dict)

        # Set the previous statuses to be the current statuses
        HexrdConfig().set_statuses_from_prev_iconfig(prev_iconfig)

        self.finished.emit()

    @property
    def overlays(self):
        return HexrdConfig().overlays

    @property
    def visible_overlays(self):
        return [x for x in self.overlays if x['visible']]

    @property
    def visible_powder_overlays(self):
        overlays = self.visible_overlays
        return [x for x in overlays if x['type'] == OverlayType.powder]

    @property
    def active_overlay(self):
        overlays = self.visible_powder_overlays
        return overlays[0] if overlays else None

    @property
    def material(self):
        overlay = self.active_overlay
        return HexrdConfig().material(overlay['material']) if overlay else None

    @property
    def active_overlay_refinements(self):
        return [x[1] for x in self.overlay_refinements(self.active_overlay)]

    def overlay_refinements(self, overlay):
        refinements = overlay.get('refinements')
        if refinements is None:
            refinements = default_overlay_refinements(overlay)
        return refinements

    @property
    def refinement_flags_without_overlays(self):
        return HexrdConfig().get_statuses_instrument_format()

    @property
    def refinement_flags(self):
        return np.hstack([self.refinement_flags_without_overlays,
                          self.active_overlay_refinements])
