from itertools import cycle
import traceback

import matplotlib.pyplot as plt
import numpy as np

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox

from hexrd.fitting.calibration import StructurelessCalibrator

from hexrdgui.calibration.calibration_dialog import (
    CalibrationDialog,
    guess_engineering_constraints,
)
from hexrdgui.calibration.calibration_dialog_callbacks import (
    CalibrationDialogCallbacks,
)
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.line_picker_dialog import LinePickerDialog
from hexrdgui.markers import igor_marker
from hexrdgui.select_item_dialog import SelectItemDialog
from hexrdgui.tree_views import GenericPicksTreeViewDialog
from hexrdgui.utils.conversions import angles_to_cart, cart_to_angles
from hexrdgui.utils.dialog import add_help_url
from hexrdgui.utils.tth_distortion import apply_tth_distortion_if_needed

from .picks_io import load_picks_from_file, save_picks_to_file


class StructurelessCalibrationRunner(QObject):

    instrument_updated = Signal()

    def __init__(self, canvas, async_runner, parent=None):
        super().__init__(parent)

        self.canvas = canvas
        self.async_runner = async_runner
        self.parent = parent

        self._calibration_dialog = None

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
        distortion_object = HexrdConfig().polar_tth_distortion_object
        if (
                distortion_overlay is not None and
                distortion_object is distortion_overlay
           ):
            msg = (
                'tth distortion to the polar view from an overlay '
                'is not supported during structureless calibration.\n\n'
                'This will be disabled, but may be turned back on afterwards.'
            )
            QMessageBox.information(self.parent, 'HEXRD', msg)
            HexrdConfig().polar_tth_distortion_object = None

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
        if not dialog.exec():
            # User canceled
            return

        pick_methods[dialog.selected_option]()

    def use_previous_pick_points(self):
        self.show_calibration_dialog(self.previous_picks_data)

    def hand_pick_points(self):
        kwargs = {
            'canvas': self.canvas,
            'parent': self.canvas,
            'cycle_cursor_colors': True,
        }
        picker = LinePickerDialog(**kwargs)

        self.line_picker = picker
        picker.ui.setWindowTitle('Structureless Calibration')

        # Add the help url
        add_help_url(picker.ui.button_box, 'calibration/structureless/')

        # We don't support viewing these yet, so hide it
        picker.ui.view_picks.setVisible(False)
        picker.start_new_line_label = (
            'Right-click to move on to the next ring.'
        )

        ring_idx = 0

        def increment_pick_label():
            nonlocal ring_idx
            ring_idx += 1
            text = f'Picking Debye-Scherrer ring: {ring_idx}'
            picker.current_pick_label = text

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
                validate_picks(calibration_lines, self.instr)
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

        engineering_constraints = guess_engineering_constraints(self.instr)

        # Create the structureless calibrator with the data
        # FIXME: add the tth_distortion dict here, if present
        kwargs = {
            'instr': self.instr,
            'data': calibrator_lines,
            'engineering_constraints': engineering_constraints,
            'euler_convention': HexrdConfig().euler_angle_convention,
        }
        self.calibrator = StructurelessCalibrator(**kwargs)

        def format_extra_params_func(params_dict, tree_dict,
                                     create_param_item):
            # Make the debye scherrer ring means
            key = 'Debye-Scherrer ring means'
            template = 'DS_ring_{i}'
            i = 0
            current = template.format(i=i)
            while current in params_dict:
                param = params_dict[current]
                # Wait to create this dict until now
                # (when we know that we have at least one parameter)
                this_dict = tree_dict.setdefault(key, {})
                this_dict[i + 1] = create_param_item(param)
                i += 1
                current = template.format(i=i)

        # Now show the calibration dialog
        kwargs = {
            'instr': self.instr,
            'params_dict': self.calibrator.params,
            'format_extra_params_func': format_extra_params_func,
            'parent': self.parent,
            'engineering_constraints': engineering_constraints,
            'window_title': 'Structureless Calibration Dialog',
            'help_url': 'calibration/structureless'
        }
        dialog = CalibrationDialog(**kwargs)

        # Connect interactions to functions
        self._dialog_callback_handler = StructurelessCalibrationCallbacks(
            dialog, self.calibrator, self.instr, self.async_runner)
        self._dialog_callback_handler.instrument_updated.connect(
            self.instrument_updated.emit)
        dialog.show()

        self._calibration_dialog = dialog

        # Ensure focus mode is on
        # Do this as a last step, so that if an exception occurs earlier,
        # the program won't be left in an invalid state.
        self.set_focus_mode(True)

        return dialog

    @property
    def previous_picks_data(self):
        name = '_previous_structureless_calibration_picks_data'
        return getattr(HexrdConfig(), name, None)

    @previous_picks_data.setter
    def previous_picks_data(self, v):
        name = '_previous_structureless_calibration_picks_data'
        setattr(HexrdConfig(), name, v)

    @property
    def file_dialog_parent(self):
        # Use the calibration dialog as the parent if possible.
        # Otherwise, just use our parent.
        dialog = self._calibration_dialog
        return dialog.ui if dialog else self.canvas


def polar_lines_to_cart(data, instr):
    calibrator_lines = []
    off_panel = []
    for line in data:
        line = np.asarray(line)
        if line.size == 0:
            continue

        line = apply_tth_distortion_if_needed(line, in_degrees=True,
                                              reverse=True)

        calibrator_line = {}
        panel_found = np.zeros(line.shape[0], dtype=bool)
        for det_key, panel in instr.detectors.items():
            points = angles_to_cart(line, panel, tvec_c=instr.tvec)
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
        points = apply_tth_distortion_if_needed(points, in_degrees=True)
        output.append(points)

    return output


def validate_picks(picks, instr):
    # Verify that the detector keys match up
    for det_lines in picks:
        for det_key in det_lines:
            if det_key not in instr.detectors:
                dets_str = ', '.join(instr.detectors)
                msg = (
                    f'Detector "{det_key}" does not match current '
                    f'detectors "{dets_str}"'
                )
                raise Exception(msg)


class StructurelessCalibrationCallbacks(CalibrationDialogCallbacks):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.edit_picks_dialog = None
        self.edit_picks_dictionary = None

    @property
    def calibrator_lines(self):
        return self.calibrator.data

    def draw_picks_on_canvas(self):
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

    def on_edit_picks_clicked(self):
        # Convert to polar lines
        data = cart_to_polar_lines(self.calibrator_lines, self.instr)

        # Convert to lists
        for i in range(len(data)):
            data[i] = data[i].tolist()

        # Now convert to a dictionary for the line labels
        dictionary = {}
        for ring_idx, v in enumerate(data):
            name = f'DS ring {ring_idx + 1}'
            dictionary[name] = data[ring_idx]

        def new_line_name_generator():
            nonlocal ring_idx
            ring_idx += 1
            return f'DS ring {ring_idx + 1}'

        dialog = GenericPicksTreeViewDialog(dictionary, canvas=self.canvas,
                                            parent=self.canvas)
        dialog.tree_view.new_line_name_generator = new_line_name_generator
        dialog.accepted.connect(self.on_edit_picks_accepted)
        dialog.finished.connect(self.on_edit_picks_finished)
        dialog.show()

        self.edit_picks_dictionary = dictionary
        self.edit_picks_dialog = dialog

        self.clear_drawn_picks()
        self.dialog.hide()

    def on_edit_picks_accepted(self):
        lines = list(self.edit_picks_dictionary.values())
        # Convert back to lines in cartesian coords
        # lines = list(dictionary.values())
        cart = polar_lines_to_cart(lines, self.instr)
        self.set_picks(cart)

    def save_picks_to_file(self, selected_file):
        save_picks_to_file(self.calibrator_lines, selected_file)

    def load_picks_from_file(self, selected_file):
        return load_picks_from_file(selected_file)

    def set_picks(self, picks):
        self.validate_picks(picks)
        self.calibrator.data = picks

        # Update the dialog
        self.clear_drawn_picks()
        self.dialog.params_dict = self.calibrator.params

        self.redraw_picks()

    def validate_picks(self, picks):
        return validate_picks(picks, self.instr)
