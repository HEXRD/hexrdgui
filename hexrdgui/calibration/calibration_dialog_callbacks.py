from abc import abstractmethod
import copy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils import instr_to_internal_dict
from hexrdgui.utils.abc_qobject import ABCQObject


class CalibrationDialogCallbacks(ABCQObject):
    """A class with default behavior for calibration dialog callbacks"""

    # This gets emitted when the instrument is updated
    # (which also happens after the other params are updated too)
    instrument_updated = Signal()

    def __init__(self, dialog, calibrator, instr, async_runner):
        super().__init__(dialog.ui)
        self.dialog = dialog
        self.calibrator = calibrator
        self.instr = instr
        self.async_runner = async_runner

        self.drawing_picks = True

        self.draw_picks_lines = []
        self.undo_stack = []

        self.round_param_numbers()
        # Make sure the tree view is updated
        self.dialog.update_tree_view()

        self.draw_picks()
        self.setup_connections()

    def setup_connections(self):
        dialog = self.dialog

        dialog.ui.draw_picks.setChecked(self.drawing_picks)
        dialog.draw_picks_toggled.connect(self.draw_picks)
        dialog.edit_picks_clicked.connect(self.on_edit_picks_clicked)
        dialog.save_picks_clicked.connect(self.on_save_picks_clicked)
        dialog.load_picks_clicked.connect(self.on_load_picks_clicked)
        dialog.engineering_constraints_changed.connect(
            self.on_engineering_constraints_changed)
        dialog.run.connect(self.on_run_clicked)
        dialog.undo_run.connect(self.on_undo_run_clicked)
        dialog.finished.connect(self.on_finished)

        HexrdConfig().image_view_loaded.connect(self.on_image_view_loaded)

    @property
    def canvas(self):
        return HexrdConfig().active_canvas

    @abstractmethod
    def draw_picks_on_canvas(self):
        pass

    @abstractmethod
    def on_edit_picks_clicked(self):
        pass

    @abstractmethod
    def on_edit_picks_accepted(self):
        pass

    @abstractmethod
    def save_picks_to_file(self):
        pass

    @abstractmethod
    def load_picks_from_file(self):
        pass

    @abstractmethod
    def validate_picks(self, picks):
        pass

    @abstractmethod
    def set_picks(self, picks):
        pass

    def set_focus_mode(self, b):
        # This will disable some widgets in the GUI during focus mode
        # Be very careful to make sure focus mode won't be set permanently
        # if an exception occurs, or else this will ruin the user's session.
        # Therefore, this should only be turned on during important moments,
        # such as when a dialog is showing, and turned off during processing.
        HexrdConfig().enable_canvas_focus_mode.emit(b)

    def on_image_view_loaded(self, img_dict):
        # If the image view is modified, it may have been because of
        # edits to tth distortion, so we should redraw the picks.
        self.redraw_picks()

    def update_dialog_from_calibrator(self):
        self.dialog.update_from_calibrator(self.calibrator)

    def push_undo_stack(self):
        stack_item = {
            'engineering_constraints': self.calibrator.engineering_constraints,
            'tth_distortion': self.calibrator.tth_distortion,
            'params': self.calibrator.params,
            'advanced_options': self.dialog.advanced_options,
        }
        # Make deep copies to ensure originals will not be edited
        stack_item = {k: copy.deepcopy(v) for k, v in stack_item.items()}

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
        for k in calibrator_items:
            v = stack_item[k]
            setattr(self.calibrator, k, v)

        self.instr.update_from_lmfit_parameter_list(self.calibrator.params)
        self.update_config_from_instrument()
        self.update_dialog_from_calibrator()
        self.dialog.advanced_options = stack_item['advanced_options']

        self.update_undo_enable_state()

    def update_undo_enable_state(self):
        self.dialog.undo_enabled = bool(self.undo_stack)

    def on_engineering_constraints_changed(self, new_constraint):
        self.calibrator.engineering_constraints = new_constraint

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

        for param_key, param in self.dialog.params_dict.items():
            if param_key in self.calibrator.params:
                current = self.calibrator.params[param_key]
                for attr in to_remember:
                    setattr(current, attr, getattr(param, attr))

        self.dialog.params_dict = self.calibrator.params

    def on_run_clicked(self):
        self.async_runner.progress_title = 'Running calibration...'
        self.async_runner.success_callback = self.on_calibration_finished
        self.async_runner.run(self.run_calibration)

    def on_undo_run_clicked(self):
        print('Undo changes')
        self.pop_undo_stack()

    def clear_drawn_picks(self):
        while self.draw_picks_lines:
            self.draw_picks_lines.pop(0).remove()

        self.canvas.draw_idle()

    def redraw_picks(self):
        self.draw_picks(self.drawing_picks)

    def draw_picks(self, b=True):
        self.drawing_picks = b
        self.clear_drawn_picks()

        if not b:
            return

        self.draw_picks_on_canvas()

    def run_calibration(self, **extra_kwargs):
        # Update the tth distortion on the calibrator from the dialog
        self.update_tth_distortion_from_dialog()

        # Add the current parameters to the undo stack
        self.push_undo_stack()

        odict = copy.deepcopy(self.dialog.advanced_options)

        x0 = self.calibrator.params.valuesdict()
        result = self.calibrator.run_calibration(odict=odict, **extra_kwargs)

        # Round the calibrator numbers to 3 decimal places
        self.round_param_numbers()

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

    def on_calibration_finished(self):
        self.update_config_from_instrument()

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

        # Update the drawn picks with their new locations
        self.redraw_picks()

    def update_refinements_tree_view(self):
        self.dialog.params_dict = self.calibrator.params

    def update_tth_distortion_from_dialog(self):
        self.calibrator.tth_distortion = self.dialog.tth_distortion

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

    def on_edit_picks_finished(self):
        # Show this again
        self.dialog.show()
        self.redraw_picks()

    def on_save_picks_clicked(self):
        title = 'Save Picks'

        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.dialog.ui, title, HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            # The user canceled
            return

        self.save_picks_to_file(selected_file)

    def on_load_picks_clicked(self):
        title = 'Load Picks'

        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.dialog.ui, title, HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            # The user canceled
            return

        picks = self.load_picks_from_file(selected_file)
        self.set_picks(picks)

    def on_finished(self):
        self.draw_picks(False)
        # Ensure focus mode is off (even if it wasn't set)
        self.set_focus_mode(False)
