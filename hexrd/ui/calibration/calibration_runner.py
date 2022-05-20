import copy
from functools import partial

import numpy as np

from PySide2.QtCore import QObject, Signal
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import QMessageBox

from hexrd.crystallography import hklToStr
from hexrd.fitting.calibration import InstrumentCalibrator, PowderCalibrator

from hexrd.ui.calibration.auto import PowderCalibrationDialog
from hexrd.ui.calibration.laue_auto_picker_dialog import LaueAutoPickerDialog
from hexrd.ui.calibration.pick_based_calibration import (
    LaueCalibrator,
    run_calibration,
)
from hexrd.ui.calibration.picks_tree_view_dialog import (
    generate_picks_results, PicksTreeViewDialog, overlays_to_tree_format,
    tree_format_to_picks,
)
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.constants import OverlayType, ViewType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.line_picker_dialog import LinePickerDialog
from hexrd.ui.utils import (
    array_index_in_list, instr_to_internal_dict, unique_array_list
)
from hexrd.ui.utils.conversions import cart_to_angles


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
        self.clear_all_overlay_picks()
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

        title = self.active_overlay.name

        box = QMessageBox(self.canvas)
        box.setIcon(QMessageBox.Question)

        # Hacky, but we'll hook up apply and yes for the buttons...
        auto_button_type = QMessageBox.Apply
        hand_button_type = QMessageBox.Yes
        buttons = auto_button_type | hand_button_type | QMessageBox.No
        box.setStandardButtons(buttons)
        # Hide the no button. We still need it, though, for canceling...
        box.button(QMessageBox.No).hide()
        msg = (
            f'Auto picking is available for "{title}"\n\n'
            'Would you like to auto pick or hand pick points?'
        )
        box.setWindowTitle(f'Select picking style for: "{title}"')
        box.setText(msg)

        auto_button = box.button(auto_button_type)
        auto_button.setText('Auto')
        auto_button.setIcon(QIcon())
        hand_button = box.button(hand_button_type)
        hand_button.setText('Hand')
        hand_button.setIcon(QIcon())
        box.exec_()

        if box.clickedButton() == auto_button:
            self.auto_pick_points()
        elif box.clickedButton() == hand_button:
            self.hand_pick_points()
        else:
            # User canceled
            self.restore_state()

    def hand_pick_points(self):
        overlay = self.active_overlay
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
        picker.finished.connect(self.calibration_line_picker_finished)
        picker.view_picks.connect(self.on_view_picks_clicked)
        picker.accepted.connect(self.finish_line)

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
        dialog = PicksTreeViewDialog(**kwargs)
        dialog.ui.show()

        kwargs = {
            'dialog': dialog,
            'highlighting': highlighting,
            'prev_visibilities': prev_visibilities,
        }
        finished_func = partial(self.finished_viewing_picks, **kwargs)
        dialog.ui.finished.connect(finished_func)

        return dialog

    def finished_viewing_picks(self, result, dialog, highlighting,
                               prev_visibilities):
        # Update all of the picks with the modified data
        updated_picks = tree_format_to_picks(dialog.dictionary)
        for i, new_picks in enumerate(updated_picks):
            self.active_overlays[i].calibration_picks = new_picks['picks']

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

        instr_calibrator = run_calibration(picks, instr, materials)
        self.write_instrument_to_hexrd_config(instr)

        # Update the lattice parameters and overlays
        overlays = self.active_overlays
        for overlay, calibrator in zip(overlays, instr_calibrator.calibrators):
            if calibrator.calibrator_type == 'powder':
                if calibrator.params.size == 0:
                    continue

                mat_name = overlay.material_name
                mat = materials[mat_name]
                mat.latticeParameters = calibrator.params
                HexrdConfig().flag_overlay_updates_for_material(mat_name)
                if mat is HexrdConfig().active_material:
                    HexrdConfig().active_material_modified.emit()
            elif calibrator.calibrator_type == 'laue':
                overlay.crystal_params = calibrator.params

        # In case any overlays changed
        HexrdConfig().overlay_config_changed.emit()
        HexrdConfig().update_overlay_editor.emit()
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
        calibration_picks = self.active_overlay.calibration_picks
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
        self.active_overlay.calibration_picks = copy.deepcopy(
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
        prev_overlay_ind = self.current_overlay_ind
        prev_overlay_data_ind = self.overlay_data_index

        if self.current_overlay_ind == -1:
            self.next_overlay()

        cur_overlay = self.active_overlay
        while cur_overlay is not None:
            # This will give us the default picks
            self.reset_overlay_picks()

            # Re-create the map that we use for indexing into the data
            self.reset_overlay_data_index_map()

            # Perform the padding
            self.pad_data_with_empty_lists()

            # Save the padded list to the current overlays
            self.save_overlay_picks()

            # Move on to the next overlay
            cur_overlay = self.next_overlay()

        self.current_overlay_ind = prev_overlay_ind
        self.overlay_data_index = prev_overlay_data_ind
        self.reset_overlay_picks()

    def pad_data_with_empty_lists(self):
        if self.overlay_data_index == -1:
            self.overlay_data_index += 1

        # This increments the overlay data index to the end and inserts
        # empty lists along the way.
        if self.active_overlay.is_powder:
            while self.current_data_path is not None:
                # This will automatically insert a list for powder
                self.current_data_list
                self.overlay_data_index += 1
        elif self.active_overlay.is_laue:
            while self.current_data_path is not None:
                # Use NaN's to indicate a skip for laue
                self.current_data_list
                self.overlay_data_index += 1

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

            # In case a point was over-written, force an update of
            # the line artists.
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
            self.current_data_list.pop(-1)
        elif self.active_overlay.is_laue:
            self.decrement_overlay_data_index()
            _, _, ind = self.current_data_path
            if 0 <= ind < len(self.current_data_list):
                self.current_data_list[ind] = (np.nan, np.nan)

    def disable_line_picker(self, b=True):
        if self.line_picker:
            self.line_picker.disabled = b
            self.line_picker.ui.setVisible(not b)

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

        self.line_picker.current_hkl_label = label

    def update_lines_from_picks(self):
        if not self.line_picker:
            return

        # Save the previous index
        prev_data_index = self.overlay_data_index

        picker = self.line_picker
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
        picker.canvas.draw_idle()

    def auto_pick_points(self):
        funcs = {
            OverlayType.powder: self.auto_pick_powder_points,
            OverlayType.laue: self.auto_pick_laue_points,
        }

        if self.active_overlay.type not in funcs:
            raise NotImplementedError(self.active_overlay.type)

        return funcs[self.active_overlay.type]()

    def auto_pick_powder_points(self):
        material = self.active_overlay.material
        dialog = PowderCalibrationDialog(material, self.canvas)
        dialog.show_optimization_parameters(False)
        if not dialog.exec_():
            # User canceled
            self.restore_state()
            return

        # The options they chose are saved here
        options = HexrdConfig().config['calibration']['powder']
        self.instr = create_hedm_instrument()

        # Assume there is only one image in each image series for now...
        img_dict = {k: x[0] for k, x in HexrdConfig().imageseries_dict.items()}

        statuses = HexrdConfig().get_statuses_instrument_format()
        self.instr.calibration_flags = statuses

        all_flags = np.hstack([statuses, self.active_overlay.refinements])
        kwargs = {
            'instr': self.instr,
            'plane_data': material.planeData,
            'img_dict': img_dict,
            'flags': all_flags,
            'eta_tol': options['eta_tol'],
            'pktype': options['pk_type'],
            'bgtype': options['bg_type'],
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
        # We are only doing a single material. Grab the only element...
        return self.auto_ic.extract_points(**kwargs)[0]

    def auto_powder_pick_finished(self, auto_picks):
        picks = auto_powder_picks_to_picks(auto_picks, self.active_overlay)
        self.overlay_picks = picks['picks']
        self.save_overlay_picks()

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
        # Assume there is only one image in each image series for now...
        imsd = HexrdConfig().imageseries_dict
        raw_img_dict = {k: x[0] for k, x in imsd.items()}

        # These are the options the user chose earlier...
        options = HexrdConfig().config['calibration']['laue_auto_picker']
        kwargs = {
            'raw_img_dict': raw_img_dict,
            **options
        }
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


def auto_powder_picks_to_picks(auto_picks, overlay):
    hkls = overlay.hkls
    picks = {det: [[] for _ in val] for det, val in hkls.items()}
    for det, det_picks in auto_picks.items():
        for nested_picks in det_picks:
            for entry in nested_picks:
                cart = entry[:2]
                hkl = entry[3:6].astype(int).tolist()
                idx = hkls[det].index(hkl)
                picks[det][idx].append(cart)

    # Now convert the cartesian coordinates to polar
    instr = create_hedm_instrument()
    for det, det_picks in picks.items():
        kwargs = {
            'panel': instr.detectors[det],
            'eta_period': HexrdConfig().polar_res_eta_period,
            'tvec_s': instr.tvec,
        }
        for i, line in enumerate(det_picks):
            det_picks[i] = cart_to_angles(line, **kwargs).tolist()

    return {
        'material': overlay.material_name,
        'type': overlay.type,
        'hkls': hkls,
        'picks': picks,
    }


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
