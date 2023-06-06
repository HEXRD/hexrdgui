import copy
from itertools import cycle
import traceback

import matplotlib.pyplot as plt
import numpy as np

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QFileDialog, QMessageBox

from hexrd.fitting.calibration import StructureLessCalibrator

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.line_picker_dialog import LinePickerDialog
from hexrd.ui.markers import igor_marker
from hexrd.ui.select_item_dialog import SelectItemDialog
from hexrd.ui.tree_views import GenericPicksTreeViewDialog
from hexrd.ui.utils import instr_to_internal_dict
from hexrd.ui.utils.conversions import angles_to_cart, cart_to_angles

from .calibration_dialog import StructurelessCalibrationDialog
from .picks_io import load_picks_from_file, save_picks_to_file


class StructurelessCalibrationRunner(QObject):

    instrument_updated = Signal()

    def __init__(self, canvas, async_runner, parent=None):
        super().__init__(parent)

        self.canvas = canvas
        self.async_runner = async_runner
        self.parent = parent
        self.drawing_picks = False

        self._calibration_dialog = None
        self._edit_picks_dialog = None

        self.undo_stack = []
        self.draw_picks_lines = []

    def clear(self):
        pass

    def run(self):
        try:
            self.validate()
            self.instr = create_hedm_instrument()
            self.choose_pick_method()
        except Exception as e:
            QMessageBox.critical(self.parent, 'HEXRD', f'Error: {e}')
            traceback.print_exc()

    def validate(self):
        if HexrdConfig().show_overlays and HexrdConfig().overlays:
            msg = (
                'Overlays will be hidden during structureless calibration.\n\n'
                'To turn them back on afterward, check "Show Overlays" in the '
                'materials panel.'
            )
            QMessageBox.information(self.parent, 'HEXRD', msg)
            HexrdConfig().show_overlays = False

        distortion_overlay = HexrdConfig().polar_tth_distortion_overlay
        if distortion_overlay is not None:
            msg = (
                'WARNING: tth distortion to the polar view is not yet '
                'supported.\n\nThis will be disabled. It may be turned '
                'back on afterwards.'
            )
            QMessageBox.information(self.parent, 'HEXRD', msg)
            HexrdConfig().polar_tth_distortion_overlay = None

    def finished(self):
        self.draw_picks(False)
        self.set_focus_mode(False)

    def set_focus_mode(self, b):
        # This will disable some widgets in the GUI during focus mode
        # Be very careful to make sure focus mode won't be set permanently
        # if an exception occurs, or else this will ruin the user's session.
        # Therefore, this should only be turned on during important moments,
        # such as when a dialog is showing, and turned off during processing.
        HexrdConfig().enable_canvas_focus_mode.emit(b)

    def choose_pick_method(self):
        title = 'Pick Method for Structureless Calibration'

        pick_methods = {
            'Previous': self.use_previous_pick_points,
            'Hand': self.hand_pick_points,
            'Load': self.load_pick_points,
        }

        disable_list = []
        if not self.previous_picks_data:
            disable_list.append('Previous')

        kwargs = {
            'options': list(pick_methods),
            'disable_list': disable_list,
            'window_title': title,
            'parent': self.canvas,
        }
        dialog = SelectItemDialog(**kwargs)
        if not dialog.exec_():
            # User canceled
            return

        pick_methods[dialog.selected_option]()

    def use_previous_pick_points(self):
        self.show_calibration_dialog(self.previous_picks_data)

    def hand_pick_points(self):
        kwargs = {
            'canvas': self.canvas,
            'parent': self.canvas,
        }
        picker = LinePickerDialog(**kwargs)

        self.line_picker = picker
        picker.ui.setWindowTitle('Structureless Calibration')

        # We don't support viewing these yet, so hide it
        picker.ui.view_picks.setVisible(False)
        picker.start_new_line_label = (
            'Right-click to move on to the next ring.'
        )

        ring_idx = 0

        def increment_pick_label():
            nonlocal ring_idx
            ring_idx += 1
            picker.current_pick_label = f'Picking DS ring: {ring_idx}'

        increment_pick_label()
        picker.line_completed.connect(increment_pick_label)

        picker.start()
        picker.finished.connect(self._hand_picking_finished)
        picker.accepted.connect(self._hand_picking_accepted)

        # This will be turned off automatically when the picker finishes
        self.set_focus_mode(True)

    def load_pick_points(self):
        title = 'Load Picks for Structureless Calibration'

        # Loop until a valid file is chosen
        while True:
            # Pick from a file
            selected_file, selected_filter = QFileDialog.getOpenFileName(
                self.file_dialog_parent, title, HexrdConfig().working_dir,
                'HDF5 files (*.h5 *.hdf5)')

            if not selected_file:
                # User canceled
                return

            try:
                calibration_lines = load_picks_from_file(selected_file)
                self._validate_picks(calibration_lines)
            except Exception as e:
                QMessageBox.critical(self.parent, 'HEXRD', f'Error: {e}')
                traceback.print_exc()
                # Try again
                continue
            else:
                break

        self.show_calibration_dialog(calibration_lines)

    def _hand_picking_accepted(self):
        data = self.line_picker.line_data

        # Remove any empty lines
        data = [x for x in data if x.size != 0]

        # These points are in tth, eta. Convert these to cartesian and assign
        # points to detectors.
        calibrator_lines = polar_lines_to_cart(data, self.instr)

        self.show_calibration_dialog(calibrator_lines)

    def _hand_picking_finished(self):
        # Turn off focus mode until we get to the next step
        # This is just to ensure that if an exception occurs, the program
        # will not be left in an invalid state.
        self.set_focus_mode(False)

    def show_calibration_dialog(self, calibrator_lines):
        self.previous_picks_data = calibrator_lines

        engineering_constraints = self.guess_engineering_constraints

        # Create the structureless calibrator with the data
        # FIXME: add the tth_distortion dict here, if present
        kwargs = {
            'instr': self.instr,
            'data': calibrator_lines,
            'engineering_constraints': engineering_constraints,
        }
        self.calibrator = StructureLessCalibrator(**kwargs)

        # Round the calibrator numbers to 3 decimal places
        self.round_param_numbers(3)

        # Now show the calibration dialog
        kwargs = {
            'instr': self.instr,
            'params_dict': self.calibrator.params,
            'parent': self.parent,
            'engineering_constraints': engineering_constraints,
        }
        dialog = StructurelessCalibrationDialog(**kwargs)

        self.draw_picks(True)

        # Connect interactions to functions
        dialog.ui.draw_picks.setChecked(self.drawing_picks)
        dialog.draw_picks_toggled.connect(self.draw_picks)
        dialog.edit_picks_clicked.connect(self._on_edit_picks_clicked)
        dialog.save_picks_clicked.connect(self._on_save_picks_clicked)
        dialog.load_picks_clicked.connect(self._on_load_picks_clicked)
        dialog.engineering_constraints_changed.connect(
            self._on_engineering_constraints_changed)
        dialog.run.connect(self._on_dialog_run_clicked)
        dialog.undo_run.connect(self._on_dialog_undo_run_clicked)
        dialog.finished.connect(self._on_dialog_finished)
        dialog.show()

        self._calibration_dialog = dialog

        # Ensure focus mode is on
        # Do this as a last step, so that if an exception occurs earlier,
        # the program won't be left in an invalid state.
        self.set_focus_mode(True)

        return dialog

    def _on_edit_picks_clicked(self):
        # Convert to polar lines
        data = cart_to_polar_lines(self.calibrator_lines, self.instr)

        # Convert to lists
        for i in range(len(data)):
            data[i] = data[i].tolist()

        # Now convert to a dictionary for the line labels
        dictionary = {}
        for i, v in enumerate(data):
            name = f'DS_ring_{i + 1}'
            dictionary[name] = data[i]

        dialog = GenericPicksTreeViewDialog(dictionary, canvas=self.canvas,
                                            parent=self.canvas)
        dialog.accepted.connect(self._on_edit_picks_accepted)
        dialog.finished.connect(self._on_edit_picks_finished)
        dialog.show()

        self._edit_picks_dictionary = dictionary
        self._edit_picks_dialog = dialog

        self.clear_drawn_picks()
        self._calibration_dialog.hide()

    def _on_edit_picks_accepted(self):
        lines = list(self._edit_picks_dictionary.values())
        # Convert back to lines in cartesian coords
        # lines = list(dictionary.values())
        cart = polar_lines_to_cart(lines, self.instr)
        self._set_picks(cart)

    def _on_edit_picks_finished(self):
        # Show this again
        self._calibration_dialog.show()
        self.draw_picks(self.drawing_picks)

    def _on_save_picks_clicked(self):
        title = 'Save Picks for Structureless Calibration'

        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.file_dialog_parent, title, HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            # The user canceled
            return

        save_picks_to_file(self.calibrator_lines, selected_file)

    def _on_load_picks_clicked(self):
        title = 'Load Picks for Structureless Calibration'

        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.file_dialog_parent, title, HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            # The user canceled
            return

        picks = load_picks_from_file(selected_file)
        self._set_picks(picks)

    def _set_picks(self, picks):
        self._validate_picks(picks)
        self.calibrator.data = picks

        dialog = self._calibration_dialog
        if dialog:
            # Update the dialog
            self.clear_drawn_picks()
            dialog.params_dict = self.calibrator.params
        else:
            self.show_calibration_dialog(picks)

        self.draw_picks(self.drawing_picks)

    def _on_engineering_constraints_changed(self, new_constraint):
        self.calibrator.engineering_constraints = new_constraint
        dialog = self._calibration_dialog

        # Keep old settings in the dialog if they are present in the new params
        # Remember everything except the name (should be the same) and
        # the expression (which might be modified from the engineering
        # constraints).
        to_remember = [
            'value',
            'vary',
            'min',
            'max',
            'brute_step',
            'user_data',
        ]

        for param_key, param in dialog.params_dict.items():
            if param_key in self.calibrator.params:
                current = self.calibrator.params[param_key]
                for attr in to_remember:
                    setattr(current, attr, getattr(param, attr))

        dialog.params_dict = self.calibrator.params

    def _validate_picks(self, picks):
        # Verify that the detector keys match up
        for det_lines in picks:
            for det_key in det_lines:
                if det_key not in self.instr.detectors:
                    dets_str = ', '.join(self.instr.detectors)
                    msg = (
                        f'Detector "{det_key}" does not match current '
                        f'detectors "{dets_str}"'
                    )
                    raise Exception(msg)

    def _on_dialog_finished(self):
        # This is called when the dialog finishes.
        # Call any cleanup code.
        self.finished()

    def clear_drawn_picks(self):
        while self.draw_picks_lines:
            self.draw_picks_lines.pop(0).remove()

        self.canvas.draw_idle()

    def draw_picks(self, b=True):
        self.drawing_picks = b
        self.clear_drawn_picks()

        if not b:
            return

        line_settings = {
            'marker': igor_marker,
            'markeredgecolor': 'black',
            'markersize': 16,
            'linestyle': 'None',
        }

        prop_cycle = plt.rcParams['axes.prop_cycle']
        color_cycler = cycle(prop_cycle.by_key()['color'])

        polar_lines = cart_to_polar_lines(self.calibrator_lines, self.instr)
        for points in polar_lines:
            color = next(color_cycler)
            artist, = self.canvas.axis.plot(points[:, 0], points[:, 1],
                                            color=color, **line_settings)
            self.draw_picks_lines.append(artist)

        self.canvas.draw_idle()

    def _on_dialog_run_clicked(self):
        self.async_runner.progress_title = 'Running calibration...'
        self.async_runner.success_callback = self.update_config_from_instrument
        self.async_runner.run(self._run_calibration)

    def _on_dialog_undo_run_clicked(self):
        print('Undo changes')
        self.pop_undo_stack()

    def update_calibrator_tth_distortion(self):
        dialog = self._calibration_dialog
        if not dialog:
            return

        self.calibrator.tth_distortion = dialog.tth_distortion

    def _run_calibration(self):
        # Update the tth distortion on the calibrator from the dialog
        self.update_calibrator_tth_distortion()

        # Add the current parameters to the undo stack
        self.push_undo_stack()

        odict = self._calibration_dialog.advanced_options

        x0 = self.calibrator.params.valuesdict()
        result = self.calibrator.run_calibration(odict=odict)

        # Round the calibrator numbers to 3 decimal places
        self.round_param_numbers(3)

        x1 = result.params.valuesdict()

        results_message = 'Calibration Results:\n'
        for name in x0:
            if not result.params[name].vary:
                continue

            old = x0[name]
            new = x1[name]
            results_message += f'{name}: {old:6.3g} ---> {new:6.3g}\n'

        print(results_message)

        self.results_message = results_message

    def update_config_from_instrument(self):
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

        self.instrument_updated.emit()

        # Update the tree_view in the GUI with the new refinements
        self.update_refinements_tree_view()

        if self.drawing_picks:
            # Update the drawn picks with their new locations
            self.draw_picks()

    def update_refinements_tree_view(self):
        dialog = self._calibration_dialog
        dialog.params_dict = self.calibrator.params

    def push_undo_stack(self):
        dialog = self._calibration_dialog
        calibrator = self.calibrator
        stack_item = {
            'engineering_constraints': calibrator.engineering_constraints,
            'tth_distortion': copy.deepcopy(calibrator.tth_distortion),
            'params': copy.deepcopy(calibrator.params),
            'advanced_options': dialog.advanced_options,
        }
        self.undo_stack.append(stack_item)
        self.update_undo_enable_state()

    def pop_undo_stack(self):
        stack_item = self.undo_stack.pop(-1)

        calibrator_items = [
            'engineering_constraints',
            'tth_distortion',
            # Put this last so it will get set last
            'params',
        ]

        # Params should get set last
        calibrator = self.calibrator
        for k in calibrator_items:
            v = stack_item[k]
            setattr(calibrator, k, v)

        self.instr.update_from_lmfit_parameter_list(calibrator.params)
        self.update_config_from_instrument()

        dialog = self._calibration_dialog
        dialog.update_from_calibrator(calibrator)
        dialog.advanced_options = stack_item['advanced_options']

        self.update_undo_enable_state()

    def update_undo_enable_state(self):
        dialog = self._calibration_dialog
        dialog.undo_enabled = bool(self.undo_stack)

    @property
    def previous_picks_data(self):
        name = '_previous_calibration_picks_data'
        return getattr(HexrdConfig(), name, None)

    @previous_picks_data.setter
    def previous_picks_data(self, v):
        name = '_previous_calibration_picks_data'
        setattr(HexrdConfig(), name, v)

    @property
    def calibrator_lines(self):
        return self.calibrator.data

    @property
    def file_dialog_parent(self):
        # Use the calibration dialog as the parent if possible.
        # Otherwise, just use our parent.
        dialog = self._calibration_dialog
        return dialog.ui if dialog else self.canvas

    def round_param_numbers(self, decimals=3):
        params_dict = self.calibrator.params

        attrs = [
            'value',
            'min',
            'max',
        ]
        for param in params_dict.values():
            for attr in attrs:
                setattr(param, attr, round(getattr(param, attr), 3))

    @property
    def guess_engineering_constraints(self):
        instr_type = guess_instrument_type(self.instr)
        if instr_type == 'TARDIS':
            return 'TARDIS'

        return None


def guess_instrument_type(instr):
    tardis_detectors = [
        'IMAGE-PLATE-2',
        'IMAGE-PLATE-3',
        'IMAGE-PLATE-4',
    ]

    if any(x in instr.detectors for x in tardis_detectors):
        return 'TARDIS'

    return 'Unknown'


def polar_lines_to_cart(data, instr):
    calibrator_lines = []
    off_panel = []
    for line in data:
        line = np.asarray(line)
        if line.size == 0:
            continue

        calibrator_line = {}
        panel_found = np.zeros(line.shape[0], dtype=bool)
        for det_key, panel in instr.detectors.items():
            points = angles_to_cart(line, panel)
            _, on_panel = panel.clip_to_panel(points)
            points[~on_panel] = np.nan
            valid_points = ~np.any(np.isnan(points), axis=1)
            panel_found[valid_points] = True
            calibrator_line[det_key] = points[valid_points]

        if not np.all(panel_found):
            off_panel.append(line[~panel_found])

        calibrator_lines.append(calibrator_line)

    if off_panel:
        off_panel = np.vstack(off_panel)
        msg = (
            'Some of the points did not lie on a detector. '
            f'These points will be ignored.\n\n{off_panel}'
        )
        QMessageBox.warning(None, 'HEXRD', msg)

    return calibrator_lines


def cart_to_polar_lines(calibrator_lines, instr):
    output = []
    for line_dict in calibrator_lines:
        polar_points = []
        for det_key, points in line_dict.items():
            panel = instr.detectors[det_key]
            kwargs = {
                'panel': panel,
                'eta_period': HexrdConfig().polar_res_eta_period,
                'tvec_c': instr.tvec,
            }

            polar_points.append(cart_to_angles(points, **kwargs))

        points = np.vstack(polar_points)
        output.append(points)

    return output
