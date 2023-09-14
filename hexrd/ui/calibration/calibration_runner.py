import copy
from functools import partial
import itertools
from pathlib import Path

import h5py
import numpy as np

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QFileDialog, QMessageBox

from hexrd.crystallography import hklToStr
from hexrd.fitting.calibration import (
    InstrumentCalibrator, LaueCalibrator, PowderCalibrator
)
from hexrd.instrument import unwrap_h5_to_dict

from hexrd.ui.calibration.auto import (
    PowderCalibrationDialog,
    save_picks_to_overlay,
)
from hexrd.ui.calibration.laue_auto_picker_dialog import LaueAutoPickerDialog
from hexrd.ui.calibration.pick_based_calibration import run_calibration
from hexrd.ui.calibration.hkl_picks_tree_view_dialog import (
    generate_picks_results, overlays_to_tree_format, HKLPicksTreeViewDialog,
    picks_cartesian_to_angles, tree_format_to_picks,
)
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.constants import OverlayType, ViewType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.line_picker_dialog import LinePickerDialog
from hexrd.ui.select_item_dialog import SelectItemDialog
from hexrd.ui.utils import (
    array_index_in_list, instr_to_internal_dict,
    masks_applied_to_panel_buffers, unique_array_list
)
from hexrd.ui.utils.conversions import cart_to_angles
from hexrd.ui.utils.dicts import ensure_all_keys_match, ndarrays_to_lists


class CalibrationRunner(QObject):

    finished = Signal()

    def __init__(self, canvas, async_runner, parent=None):
        super().__init__(parent)

        self.canvas = canvas
        self.current_overlay_ind = -1
        self.overlay_data_index = -1

        self.line_picker = None

        self.async_runner = async_runner

    def run(self):
        # The active overlays will be the ones that are visible when we start
        self.active_overlays = self.visible_overlays

        self.validate()
        self.pad_overlay_picks()
        self.pick_next_line()

    def validate(self):
        active_overlays = self.active_overlays
        if not active_overlays:
            raise Exception('No visible overlays')

        if not all(x.has_widths for x in active_overlays):
            raise Exception('All visible overlays must have widths')

        flags = HexrdConfig().get_statuses_instrument_format().tolist()
        # Make sure the length of our flags matches up with the instruments
        instr = create_hedm_instrument()
        if len(flags) != len(instr.calibration_flags):
            msg = ('Length of internal flags does not match '
                   'instr.calibration_flags')
            raise Exception(msg)

        # Add overlay refinements
        for overlay in active_overlays:
            flags += overlay.refinements.tolist()

        if np.count_nonzero(flags) == 0:
            raise Exception('There are no refinable parameters')

    def enable_focus_mode(self, b):
        HexrdConfig().enable_canvas_focus_mode.emit(b)
        HexrdConfig().enable_canvas_toolbar.emit(not b)

    def clear_all_overlay_picks(self):
        for overlay in self.active_overlays:
            overlay.reset_calibration_picks()

    @property
    def overlays(self):
        return HexrdConfig().overlays

    @property
    def visible_overlays(self):
        return [x for x in self.overlays if x.visible]

    def next_overlay(self):
        self.current_overlay_ind += 1
        return self.active_overlay

    @property
    def active_overlay(self):
        if self.current_overlay_ind >= len(self.active_overlays):
            return None

        return self.active_overlays[self.current_overlay_ind]

    def pick_next_line(self):
        overlay = self.next_overlay()
        if overlay is None:
            # No more overlays to do. Move on.
            self.finish()
            return

        self.pick_this_line()

    def pick_this_line(self):
        overlay = self.active_overlay
        title = f'Pick Method for "{overlay.name}"'

        pick_methods = {
            'Current': self.use_current_pick_points,
            'Auto': self.auto_pick_points,
            'Hand': self.hand_pick_points,
            'Load': self.load_pick_points,
        }

        disable_list = []
        if not overlay.has_picks_data:
            disable_list.append('Current')

        kwargs = {
            'options': list(pick_methods.keys()),
            'disable_list': disable_list,
            'window_title': title,
            'parent': self.canvas,
        }
        dialog = SelectItemDialog(**kwargs)
        if not dialog.exec_():
            # User canceled
            self.restore_state()
            return

        pick_methods[dialog.selected_option]()

    def use_current_pick_points(self):
        self.reset_overlay_picks()
        self.finish_line()

    def hand_pick_points(self):
        overlay = self.active_overlay
        overlay.reset_calibration_picks()

        title = overlay.name

        # Only make the current overlay we are selecting visible
        self.set_exclusive_overlay_visibility(overlay)

        self.reset_overlay_picks()
        self.reset_overlay_data_index_map()
        self.increment_overlay_data_index()

        kwargs = {
            'canvas': self.canvas,
            'parent': self.canvas,
            'single_line_mode': overlay.is_laue,
        }

        picker = LinePickerDialog(**kwargs)

        self.line_picker = picker
        picker.ui.setWindowTitle(title)
        self.update_current_hkl_label()
        # In case picks were selected beforehand, make sure the lines
        # get updated every time a new line is added (the first of
        # which gets added with start()).
        picker.line_added.connect(self.update_lines_from_picks)
        picker.start()
        picker.point_picked.connect(self.point_picked)
        picker.line_completed.connect(self.line_completed)
        picker.last_point_removed.connect(self.last_point_removed)
        picker.last_line_restored.connect(self.last_line_restored)
        picker.finished.connect(self.calibration_line_picker_finished)
        picker.view_picks.connect(self.on_view_picks_clicked)
        picker.accepted.connect(self.finish_line)

        # Enable focus mode during line picking
        self.enable_focus_mode(True)

    def load_pick_points(self):
        overlay = self.active_overlay

        title = f'Load Picks for {overlay.name}'

        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.canvas, title, HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            # User canceled
            self.pick_this_line()
            return

        HexrdConfig().working_dir = str(Path(selected_file).parent)

        import_data = {}
        with h5py.File(selected_file, 'r') as rf:
            unwrap_h5_to_dict(rf, import_data)

        cart = import_data['cartesian']
        if overlay.name not in cart:
            msg = (
                f'Current overlay "{overlay.name}" was not found in '
                f'"{selected_file}" under the "/cartesian" group'
            )
            QMessageBox.critical(self.canvas, 'HEXRD', msg)
            self.pick_this_line()
            return

        imported_picks = cart[overlay.name]
        current_picks = overlays_to_tree_format([overlay])[overlay.name]

        try:
            # Ensure that all keys match (i. e., same hkl settings were used)
            sorted_picks = ensure_all_keys_match(current_picks, imported_picks)
        except KeyError as e:
            msg = (
                f'Keys on the current picks for "{overlay.name}" '
                f'did not match those found in "{selected_file}"\n'
                f'\nFull error: {e.args[0]}'
            )
            print(msg)
            QMessageBox.critical(self.canvas, 'HEXRD', msg)
            self.pick_this_line()
            return

        results = {overlay.name: sorted_picks}

        # Convert to angles, and to lists
        results = picks_cartesian_to_angles(results)
        ndarrays_to_lists(results)

        # Set the new picks on the overlay
        updated_picks = tree_format_to_picks(results)
        overlay.calibration_picks_polar = updated_picks[0]['picks']
        self.reset_overlay_picks()

        dialog = self.view_picks_table()
        dialog.ui.finished.connect(self.finish_line)

    def on_view_picks_clicked(self):
        # Save the overlay picks so that they will be displayed in the table
        self.save_overlay_picks()
        self.view_picks_table()

    def view_picks_table(self):
        # Backup some settings
        if self.active_overlay and self.active_overlay.has_highlights:
            highlighting = copy.deepcopy(self.active_overlay.highlights)
        else:
            highlighting = None

        prev_visibilities = self.overlay_visibilities
        self.restore_overlay_visibilities()
        self.disable_line_picker()

        kwargs = {
            'dictionary': overlays_to_tree_format(self.active_overlays),
            'coords_type': ViewType.polar,
            'canvas': self.canvas,
            'parent': self.canvas,
        }
        dialog = HKLPicksTreeViewDialog(**kwargs)
        dialog.ui.show()

        kwargs = {
            'dialog': dialog,
            'highlighting': highlighting,
            'prev_visibilities': prev_visibilities,
        }
        finished_func = partial(self.finished_viewing_picks, **kwargs)
        dialog.ui.finished.connect(finished_func)

        # Make sure focus mode is enabled while viewing the picks
        self.enable_focus_mode(True)

        return dialog

    def finished_viewing_picks(self, result, dialog, highlighting,
                               prev_visibilities):
        # Turn off focus mode (which may be turned back on if the line picker
        # will reappear)
        self.enable_focus_mode(False)
        # Update all of the picks with the modified data
        updated_picks = tree_format_to_picks(dialog.dictionary)
        for i, new_picks in enumerate(updated_picks):
            self.active_overlays[i].calibration_picks_polar = new_picks['picks']

        if self.active_overlay:
            self.reset_overlay_picks()

        self.update_lines_from_picks()

        # Restore backups
        self.enable_line_picker()
        if highlighting is None:
            self.remove_all_highlighting()
        else:
            self.set_highlighting(highlighting)
        self.overlay_visibilities = prev_visibilities

    def finish_line(self):
        self.save_overlay_picks()
        self.pick_next_line()

    def generate_picks_results(self):
        return generate_picks_results(self.active_overlays)

    @property
    def pick_materials(self):
        mats = [o.material for o in self.active_overlays]
        return {x.name: x for x in mats}

    def dump_results(self):
        # This dumps out all results to files for testing
        # It is mostly intended for debug purposes
        import json
        import pickle

        class NumpyEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                return json.JSONEncoder.default(self, obj)

        for name, mat in self.pick_materials.items():
            # Dump out the material
            mat_file_name = f'{name}.pkl'
            print(f'Writing out material to {mat_file_name}')
            with open(mat_file_name, 'wb') as wf:
                pickle.dump(mat, wf)

        pick_results = self.generate_picks_results()
        out_file = 'calibration_picks.json'
        print(f'Writing out picks to {out_file}')
        with open(out_file, 'w') as wf:
            json.dump(pick_results, wf, cls=NumpyEncoder)

        # Dump out the instrument as well
        instr = create_hedm_instrument()
        print('Writing out instrument to instrument.pkl')
        with open('instrument.pkl', 'wb') as wf:
            pickle.dump(instr, wf)

        # Dump out refinement flags
        flags = HexrdConfig().get_statuses_instrument_format()
        print('Writing out refinement flags to refinement_flags.json')
        with open('refinement_flags.json', 'w') as wf:
            json.dump(flags, wf, cls=NumpyEncoder)

    def finish(self):
        # Ensure the line picker is disabled and gone
        self.disable_line_picker()
        self.line_picker = None

        # Ask the user if they want to review the picks
        msg = 'Point picking complete. Review picks?'
        response = QMessageBox.question(self.canvas, 'HEXRD', msg)
        if response == QMessageBox.Yes:
            dialog = self.view_picks_table()
            # Make sure the button box is shown. We will only proceed
            # if the user accepts the dialog.
            dialog.button_box_visible = True
            dialog.ui.accepted.connect(self.run_calibration)
        else:
            self.run_calibration()

    def run_calibration(self):
        picks = self.generate_picks_results()
        materials = self.pick_materials
        instr = create_hedm_instrument()
        flags = HexrdConfig().get_statuses_instrument_format()
        instr.calibration_flags = flags

        img_dict = HexrdConfig().masked_images_dict

        instr_calibrator = run_calibration(picks, instr, img_dict, materials)
        self.write_instrument_to_hexrd_config(instr)

        # Update the lattice parameters and overlays
        overlays = self.active_overlays
        for overlay, calibrator in zip(overlays, instr_calibrator.calibrators):
            if isinstance(calibrator, PowderCalibrator):
                if calibrator.params.size == 0:
                    continue

                mat_name = overlay.material_name
                mat = materials[mat_name]
                mat.latticeParameters = calibrator.params
                HexrdConfig().flag_overlay_updates_for_material(mat_name)
                HexrdConfig().material_modified.emit(mat_name)
            else:
                overlay.crystal_params = calibrator.params

        # In case any overlays changed
        HexrdConfig().overlay_config_changed.emit()
        HexrdConfig().update_overlay_editor.emit()

        # Focus mode should definitely not be enabled at this point,
        # but let's be extra careful and make sure it is disabled.
        self.enable_focus_mode(False)

        self.finished.emit()

    def write_instrument_to_hexrd_config(self, instr):
        output_dict = instr_to_internal_dict(instr)

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

    def set_exclusive_overlay_visibility(self, overlay):
        self.overlay_visibilities = [overlay is x for x in self.overlays]

    def calibration_line_picker_finished(self):
        self.restore_state()

    def restore_state(self):
        self.enable_focus_mode(False)
        self.restore_overlay_visibilities()
        self.remove_all_highlighting()

    def restore_overlay_visibilities(self):
        is_visible = [x in self.active_overlays for x in self.overlays]
        self.overlay_visibilities = is_visible
        HexrdConfig().overlay_config_changed.emit()

    def set_highlighting(self, highlighting):
        self.active_overlay.highlights = highlighting
        HexrdConfig().flag_overlay_updates_for_all_materials()
        HexrdConfig().overlay_config_changed.emit()

    def remove_all_highlighting(self):
        for overlay in self.overlays:
            overlay.clear_highlights()
        HexrdConfig().flag_overlay_updates_for_all_materials()
        HexrdConfig().overlay_config_changed.emit()

    @property
    def overlay_visibilities(self):
        return [x.visible for x in self.overlays]

    @overlay_visibilities.setter
    def overlay_visibilities(self, visibilities):
        for o, v in zip(self.overlays, visibilities):
            o.visible = v
        HexrdConfig().overlay_config_changed.emit()

    def reset_overlay_picks(self):
        calibration_picks = self.active_overlay.calibration_picks_polar
        self.overlay_picks = copy.deepcopy(calibration_picks)

    def reset_overlay_data_index_map(self):
        self.overlay_data_index = -1

        data_key_map = {
            OverlayType.powder: 'rings',
            OverlayType.laue: 'spots',
        }

        if self.active_overlay.type not in data_key_map:
            raise Exception(f'{self.active_overlay.type} not implemented')

        data_key = data_key_map[self.active_overlay.type]
        data = self.active_overlay.data

        data_map = {}
        ind = 0
        if self.active_overlay.is_powder:
            # Order by rings, then detector
            # First, gather all of the hkls
            # We can't use a set() because we can't use a normal comparison
            # operator for the numpy arrays.
            hkl_list = []
            for value in data.values():
                hkl_list.extend(value['hkls'])
            hkl_list = unique_array_list(hkl_list)

            # Sort the hkls list by min two theta
            min_tth_values = []
            for hkl in hkl_list:
                min_value = np.finfo(np.float64).max
                for key in data.keys():
                    hkl_index = array_index_in_list(hkl, data[key]['hkls'])
                    if hkl_index == -1:
                        continue

                    tth_values = data[key][data_key][hkl_index][:, 1]
                    min_value = min(min_value, np.nanmin(tth_values))

                min_tth_values.append(min_value)

            # Perform the sorting
            indices = list(range(len(hkl_list)))
            indices.sort(key=lambda i: min_tth_values[i])
            hkl_list = [hkl_list[i] for i in indices]

            # Next, loop over the hkls, then the detectors, and add the items
            for hkl in hkl_list:
                # Sort keys by min eta in the overlay
                keys = []
                min_eta_values = {}
                hkl_indices = {}
                for key in data.keys():
                    hkl_index = array_index_in_list(hkl, data[key]['hkls'])
                    if hkl_index == -1:
                        continue

                    rings = data[key][data_key]

                    keys.append(key)
                    min_eta_values[key] = np.nanmin(rings[hkl_index][:, 0])
                    hkl_indices[key] = hkl_index

                keys.sort(key=lambda x: min_eta_values[x])

                for key in keys:
                    data_map[ind] = (key, data_key, hkl_indices[key])
                    ind += 1

        elif self.active_overlay.is_laue:
            # Order by detector, then spots
            for key, value in data.items():
                for i in range(len(value[data_key])):
                    data_map[ind] = (key, data_key, i)
                    ind += 1

        self.overlay_data_index_map = data_map

    def save_overlay_picks(self):
        self.active_overlay.calibration_picks_polar = copy.deepcopy(
            self.overlay_picks)

    @property
    def current_data_path(self):
        idx = self.overlay_data_index
        if not 0 <= idx < len(self.overlay_data_index_map):
            return None

        return self.overlay_data_index_map[idx]

    @property
    def current_data_list(self):
        key, _, val = self.current_data_path
        root_list = self.overlay_picks.setdefault(key, [])
        if self.active_overlay.is_powder:
            while len(root_list) <= val:
                root_list.append([])
            return root_list[val]
        elif self.active_overlay.is_laue:
            # Only a single list for each Laue key
            # Make sure it contains a value for the requested path
            while len(root_list) < val + 1:
                root_list.append((np.nan, np.nan))

            return root_list

        raise Exception(f'Not implemented: {self.active_overlay.type}')

    def pad_overlay_picks(self):
        for overlay in self.active_overlays:
            overlay.pad_picks_data()

        self.reset_overlay_picks()

    def increment_overlay_data_index(self):
        self.overlay_data_index += 1
        data_path = self.current_data_path
        if data_path is None:
            # We are done picking for this overlay.
            if self.line_picker:
                self.line_picker.ui.accept()
            return

        self.set_highlighting([data_path])

        if self.active_overlay.is_powder:
            # Make sure a list is automatically inserted for powder
            self.current_data_list

        # Update the hkl label
        self.update_current_hkl_label()

    def decrement_overlay_data_index(self):
        if self.overlay_data_index == 0:
            # Can't go back any further
            return

        self.overlay_data_index -= 1
        data_path = self.current_data_path
        self.set_highlighting([data_path])

    def point_picked(self, x, y):
        data = (x, y)
        if self.active_overlay.is_powder:
            self.current_data_list.append(data)
        elif self.active_overlay.is_laue:
            _, _, ind = self.current_data_path
            self.current_data_list[ind] = data
            self.increment_overlay_data_index()

            # The line builder doesn't accurately update the lines
            # during Laue picking, so we force it here.
            self.update_lines_from_picks()

    def line_completed(self):
        self.increment_overlay_data_index()

    def last_point_removed(self):
        if self.active_overlay.is_powder:
            if len(self.current_data_list) == 0:
                # Go back one line
                self.decrement_overlay_data_index()
            if len(self.current_data_list) == 0:
                # Still nothing to do
                return
            # Remove the last point of data
            self.current_data_list.pop()
        elif self.active_overlay.is_laue:
            self.decrement_overlay_data_index()
            _, _, ind = self.current_data_path
            if 0 <= ind < len(self.current_data_list):
                self.current_data_list[ind] = (np.nan, np.nan)

            # The line builder doesn't accurately update the lines
            # during Laue picking, so we force it here.
            self.update_lines_from_picks()

    def last_line_restored(self):
        # This should only be called for powder overlays, because
        # Laue overlays are single-line
        while self.current_data_list:
            self.current_data_list.pop()

        # Go back one line
        self.decrement_overlay_data_index()

    def disable_line_picker(self, b=True):
        if self.line_picker:
            self.line_picker.disabled = b
            self.line_picker.ui.setVisible(not b)

            # Make sure focus mode is enabled while the line picker is visible
            self.enable_focus_mode(not b)

    def enable_line_picker(self):
        self.disable_line_picker(False)

    def update_current_hkl_label(self):
        if not self.line_picker or not self.active_overlay:
            return

        overlay = self.active_overlay
        path = list(self.current_data_path)
        path[1] = 'hkls'
        cur = overlay.data
        for entry in path:
            cur = cur[entry]

        hkl = hklToStr(cur)
        label = f'Current hkl:  {hkl}'
        if overlay.is_laue:
            data_list = self.current_data_list
            if self.overlay_data_index < len(data_list):
                data_entry = data_list[self.overlay_data_index]
                if not any(np.isnan(x) for x in data_entry):
                    label += '  (overwriting)'

        self.line_picker.current_pick_label = label

    def update_lines_from_picks(self):
        if not self.line_picker:
            return

        picker = self.line_picker
        if self.active_overlay.is_powder:
            # Save the previous index
            prev_data_index = self.overlay_data_index
            for i, line in enumerate(picker.lines):
                self.overlay_data_index = i
                if not self.current_data_path:
                    break

                if self.current_data_list:
                    data = list(zip(*self.current_data_list))
                else:
                    data = [(), ()]

                line.set_data(data)

            self.overlay_data_index = prev_data_index
        else:
            # For Laue, there should be just one line that contains
            # all of the points.
            data = list(zip(*itertools.chain(*self.overlay_picks.values())))
            picker.lines[0].set_data(data)

        picker.canvas.draw_idle()

    def auto_pick_points(self):
        overlay = self.active_overlay

        funcs = {
            OverlayType.powder: self.auto_pick_powder_points,
            OverlayType.laue: self.auto_pick_laue_points,
        }

        if overlay.type not in funcs:
            raise NotImplementedError(overlay.type)

        overlay.reset_calibration_picks()
        return funcs[overlay.type]()

    def auto_pick_powder_points(self):
        overlay = self.active_overlay
        material = overlay.material
        dialog = PowderCalibrationDialog(material, self.canvas)
        dialog.show_optimization_parameters(False)
        if not dialog.exec_():
            # User canceled
            self.restore_state()
            return

        # The options they chose are saved here
        options = HexrdConfig().config['calibration']['powder']
        self.instr = create_hedm_instrument()

        img_dict = HexrdConfig().masked_images_dict

        statuses = HexrdConfig().get_statuses_instrument_format()
        self.instr.calibration_flags = statuses

        all_flags = np.hstack([statuses, overlay.refinements])
        kwargs = {
            'instr': self.instr,
            'plane_data': material.planeData,
            'img_dict': img_dict,
            'flags': all_flags,
            'eta_tol': options['eta_tol'],
            'pktype': options['pk_type'],
            'bgtype': options['bg_type'],
            'tth_distortion': overlay.tth_distortion_dict,
        }

        self.auto_pc = PowderCalibrator(**kwargs)
        self.auto_ic = InstrumentCalibrator(self.auto_pc)
        self.auto_pick_powder_lines()

    def auto_pick_powder_lines(self):
        self.async_runner.progress_title = 'Auto picking points...'
        self.async_runner.success_callback = self.auto_powder_pick_finished
        self.async_runner.run(self.run_auto_powder_pick)

    def run_auto_powder_pick(self):
        options = HexrdConfig().config['calibration']['powder']
        kwargs = {
            'fit_tth_tol': options['fit_tth_tol'],
            'int_cutoff': options['int_cutoff'],
        }
        # Apply any masks to the panel buffer for our instrument.
        # This is done so that the auto picking will skip over masked regions.
        with masks_applied_to_panel_buffers(self.instr):
            # We are only doing a single material. Grab the only element...
            return self.auto_ic.extract_points(**kwargs)[0]

    def auto_powder_pick_finished(self, auto_picks):
        save_picks_to_overlay(self.active_overlay, auto_picks)
        self.reset_overlay_picks()

        if len(self.active_overlays) == 1:
            # If this is the only overlay, don't view the picks table,
            # as the GUI will ask anyways...
            self.finish_line()
        else:
            dialog = self.view_picks_table()
            dialog.ui.finished.connect(self.finish_line)

    def auto_pick_laue_points(self):
        overlay = self.active_overlay
        dialog = LaueAutoPickerDialog(overlay, self.canvas)
        if not dialog.exec_():
            # User canceled
            self.restore_state()
            return

        self.instr = create_hedm_instrument()

        statuses = HexrdConfig().get_statuses_instrument_format()
        self.instr.calibration_flags = statuses

        all_flags = np.hstack([statuses, self.active_overlay.refinements])
        init_kwargs = {
            'instr': self.instr,
            'plane_data': overlay.plane_data,
            'grain_params': overlay.crystal_params,
            'flags': all_flags,
            'min_energy': overlay.min_energy,
            'max_energy': overlay.max_energy,
        }

        self.laue_auto_picker = LaueCalibrator(**init_kwargs)
        self.auto_pick_laue_spots()

    def auto_pick_laue_spots(self):
        self.async_runner.progress_title = 'Auto picking points...'
        self.async_runner.success_callback = self.auto_laue_pick_finished
        self.async_runner.run(self.run_auto_laue_pick)

    def run_auto_laue_pick(self):
        img_dict = HexrdConfig().masked_images_dict

        # These are the options the user chose earlier...
        options = HexrdConfig().config['calibration']['laue_auto_picker']
        kwargs = {
            'raw_img_dict': img_dict,
            **options
        }
        # Apply any masks to the panel buffer for our instrument.
        # This is done so that the auto picking will skip over masked regions.
        with masks_applied_to_panel_buffers(self.instr):
            return self.laue_auto_picker._autopick_points(**kwargs)

    def auto_laue_pick_finished(self, auto_picks):
        picks = auto_laue_picks_to_picks(auto_picks, self.active_overlay)
        self.overlay_picks = picks['picks']
        self.save_overlay_picks()

        if len(self.active_overlays) == 1:
            # If this is the only overlay, don't view the picks table,
            # as the GUI will ask anyways...
            self.finish_line()
        else:
            dialog = self.view_picks_table()
            dialog.ui.finished.connect(self.finish_line)


def auto_laue_picks_to_picks(auto_picks, overlay):
    hkls = overlay.hkls
    picks = {det: [[] for _ in val] for det, val in hkls.items()}
    for det, det_picks in auto_picks.items():
        for entry in det_picks:
            hkl = entry[1].astype(int).tolist()
            cart = entry[6]
            idx = hkls[det].index(hkl)
            picks[det][idx] = cart

    # Now convert the cartesian coordinates to polar
    instr = create_hedm_instrument()
    for det, det_picks in picks.items():
        kwargs = {
            'panel': instr.detectors[det],
            'eta_period': HexrdConfig().polar_res_eta_period,
            'tvec_c': instr.tvec,
        }
        for i, line in enumerate(det_picks):
            if len(line) == 0:
                det_picks[i] = (np.nan, np.nan)
                continue

            det_picks[i] = cart_to_angles(line, **kwargs)[0]

    return {
        'material': overlay.material_name,
        'type': overlay.type,
        'hkls': hkls,
        'picks': picks,
    }
