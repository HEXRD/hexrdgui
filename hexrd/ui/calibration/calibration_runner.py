import copy

import numpy as np

from hexrd.crystallography import hklToStr

from hexrd.ui.calibration.pick_based_calibration import run_calibration
from hexrd.ui.calibration.picks_tree_view_dialog import PicksTreeViewDialog
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.constants import OverlayType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.line_picker_dialog import LinePickerDialog
from hexrd.ui.overlays import default_overlay_refinements
from hexrd.ui.tree_views.picks_tree_view import (
    picks_to_tree_format, tree_format_to_picks
)
from hexrd.ui.utils import (
    array_index_in_list, instr_to_internal_dict, unique_array_list
)


class CalibrationRunner:
    def __init__(self, canvas, parent=None):
        self.canvas = canvas
        self.parent = parent
        self.current_overlay_ind = -1
        self.overlay_data_index = -1
        self.all_overlay_picks = {}

        self.line_picker = None

    def run(self):
        self.validate()
        self.clear_all_overlay_picks()
        self.backup_overlay_visibilities = self.overlay_visibilities
        self.pad_overlay_picks()
        self.pick_next_line()

    def validate(self):
        visible_overlays = self.visible_overlays
        if not visible_overlays:
            raise Exception('No visible overlays')

        if not all(self.has_widths(x) for x in visible_overlays):
            raise Exception('All visible overlays must have widths')

        flags = HexrdConfig().get_statuses_instrument_format().tolist()
        # Make sure the length of our flags matches up with the instruments
        instr = create_hedm_instrument()
        if len(flags) != len(instr.calibration_flags):
            msg = ('Length of internal flags does not match '
                   'instr.calibration_flags')
            raise Exception(msg)

        # Add overlay refinements
        for overlay in visible_overlays:
            flags += [x[1] for x in self.get_refinements(overlay)]

        if np.count_nonzero(flags) == 0:
            raise Exception('There are no refinable parameters')

    def clear_all_overlay_picks(self):
        self.all_overlay_picks.clear()

    @staticmethod
    def has_widths(overlay):
        type = overlay['type']
        if type == OverlayType.powder:
            # Make sure the material has a two-theta width
            name = overlay['material']
            return HexrdConfig().material(name).planeData.tThWidth is not None
        elif type == OverlayType.laue:
            options = overlay.get('options', {})
            width_params = ['tth_width', 'eta_width']
            return all(options.get(x) is not None for x in width_params)
        elif type == OverlayType.mono_rotation_series:
            raise NotImplementedError('mono_rotation_series not implemented')
        else:
            raise Exception(f'Unknown overlay type: {type}')

    @property
    def overlays(self):
        return HexrdConfig().overlays

    @property
    def visible_overlays(self):
        return [x for x in self.overlays if x['visible']]

    @staticmethod
    def overlay_name(overlay):
        return f'{overlay["material"]} {overlay["type"].name}'

    def next_overlay(self):
        ind = self.current_overlay_ind
        ind += 1
        for i in range(ind, len(self.overlays)):
            if self.overlays[i]['visible']:
                self.current_overlay_ind = i
                return self.overlays[i]

    @property
    def active_overlay(self):
        if not 0 <= self.current_overlay_ind < len(self.overlays):
            return None

        return self.overlays[self.current_overlay_ind]

    @property
    def active_overlay_type(self):
        return self.active_overlay['type']

    def pick_next_line(self):
        overlay = self.next_overlay()
        if overlay is None:
            # No more overlays to do. Move on.
            self.finish()
            return

        # Create a backup of the visibilities that we will restore later
        self.backup_overlay_visibilities = self.overlay_visibilities

        # Only make the current overlay we are selecting visible
        self.set_exclusive_overlay_visibility(overlay)

        title = self.overlay_name(overlay)

        self.reset_overlay_picks()
        self.reset_overlay_data_index_map()
        self.increment_overlay_data_index()

        kwargs = {
            'canvas': self.canvas,
            'parent': self.canvas,
            'single_line_mode': overlay['type'] == OverlayType.laue
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
        picker.view_picks.connect(self.view_picks_table)
        picker.accepted.connect(self.finish_line)

    def view_picks_table(self):
        if self.line_picker:
            parent = self.line_picker.ui
        else:
            parent = None

        # Backup some settings
        highlighting = copy.deepcopy(self.active_overlay['highlights'])
        prev_visibilities = self.overlay_visibilities
        self.restore_backup_overlay_visibilities()
        self.hide_artists()

        picks = self.generate_pick_results()
        tree_format = picks_to_tree_format(picks)
        dialog = PicksTreeViewDialog(tree_format, self.canvas, parent)
        dialog.exec_()

        # Update all of the picks with the modified data
        updated_picks = tree_format_to_picks(dialog.dictionary)

        # Since python dicts are ordered, I think we can assume that the
        # ordering of the picks should still be the same.
        for i, new_picks in enumerate(updated_picks):
            self.all_overlay_picks[i] = new_picks['picks']

        self.overlay_picks = self.all_overlay_picks[self.current_overlay_ind]
        self.update_lines_from_picks()

        # Restore backups
        self.show_artists()
        self.set_highlighting(highlighting)
        self.overlay_visibilities = prev_visibilities

    def finish_line(self):
        self.save_overlay_picks()
        self.pick_next_line()

    def get_refinements(self, overlay):
        refinements = overlay.get('refinements')
        if refinements is None:
            refinements = default_overlay_refinements(overlay)
        return refinements

    def generate_pick_results(self):

        def get_hkls(overlay):
            return {
                key: val.get('hkls', [])
                for key, val in overlay['data'].items()
            }

        pick_results = []
        for i, val in self.all_overlay_picks.items():
            overlay = self.overlays[i]
            pick_results.append({
                'material': overlay['material'],
                'type': overlay['type'].value,
                'options': overlay['options'],
                'refinements': self.get_refinements(overlay),
                'hkls': get_hkls(overlay),
                'picks': val
            })
        return pick_results

    @property
    def pick_materials(self):
        mats = [
            HexrdConfig().material(self.overlays[i]['material'])
            for i in self.all_overlay_picks
        ]
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

        pick_results = self.generate_pick_results()
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
        self.run_calibration()

    def run_calibration(self):
        picks = self.generate_pick_results()
        materials = self.pick_materials
        instr = create_hedm_instrument()
        flags = HexrdConfig().get_statuses_instrument_format()
        instr.calibration_flags = flags

        instr_calibrator = run_calibration(picks, instr, materials)
        self.write_instrument_to_hexrd_config(instr)

        # Update the lattice parameters and overlays
        overlays = [self.overlays[i] for i in self.all_overlay_picks]
        for overlay, calibrator in zip(overlays, instr_calibrator.calibrators):
            if calibrator.calibrator_type == 'powder':
                if calibrator.params.size == 0:
                    continue

                mat_name = overlay['material']
                mat = materials[mat_name]
                mat.latticeParameters = calibrator.params
                HexrdConfig().flag_overlay_updates_for_material(mat_name)
                if mat is HexrdConfig().active_material:
                    HexrdConfig().active_material_modified.emit()
            elif calibrator.calibrator_type == 'laue':
                overlay['options']['crystal_params'] = calibrator.params

        # In case any overlays changed
        HexrdConfig().overlay_config_changed.emit()
        HexrdConfig().calibration_complete.emit()

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
        self.restore_backup_overlay_visibilities()
        self.remove_all_highlighting()

    def restore_backup_overlay_visibilities(self):
        self.overlay_visibilities = self.backup_overlay_visibilities
        HexrdConfig().overlay_config_changed.emit()

    def set_highlighting(self, highlighting):
        self.active_overlay['highlights'] = highlighting
        HexrdConfig().flag_overlay_updates_for_all_materials()
        HexrdConfig().overlay_config_changed.emit()

    def remove_all_highlighting(self):
        for overlay in self.overlays:
            if 'highlights' in overlay:
                del overlay['highlights']
        HexrdConfig().flag_overlay_updates_for_all_materials()
        HexrdConfig().overlay_config_changed.emit()

    @property
    def overlay_visibilities(self):
        return [x['visible'] for x in self.overlays]

    @overlay_visibilities.setter
    def overlay_visibilities(self, visibilities):
        for o, v in zip(self.overlays, visibilities):
            o['visible'] = v
        HexrdConfig().overlay_config_changed.emit()

    def reset_overlay_picks(self):
        ind = self.current_overlay_ind
        self.overlay_picks = self.all_overlay_picks.get(ind, {})

    def reset_overlay_data_index_map(self):
        self.overlay_data_index = -1

        data_key_map = {
            OverlayType.powder: 'rings',
            OverlayType.laue: 'spots',
        }

        if self.active_overlay_type not in data_key_map:
            raise Exception(f'{self.active_overlay_type} not implemented')

        data_key = data_key_map[self.active_overlay_type]
        data = self.active_overlay['data']

        data_map = {}
        ind = 0
        if self.active_overlay_type == OverlayType.powder:
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

        elif self.active_overlay_type == OverlayType.laue:
            # Order by detector, then spots
            for key, value in data.items():
                for i in range(len(value[data_key])):
                    data_map[ind] = (key, data_key, i)
                    ind += 1

        self.overlay_data_index_map = data_map

    def save_overlay_picks(self):
        # Make sure there is at least an empty list for each detector
        for key in self.active_overlay['data'].keys():
            if key not in self.overlay_picks:
                self.overlay_picks[key] = []
        self.all_overlay_picks[self.current_overlay_ind] = self.overlay_picks

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
        if self.active_overlay_type == OverlayType.powder:
            while len(root_list) <= val:
                root_list.append([])
            return root_list[val]
        elif self.active_overlay_type == OverlayType.laue:
            # Only a single list for each Laue key
            # Make sure it contains a value for the requested path
            while len(root_list) < val + 1:
                root_list.append((np.nan, np.nan))

            return root_list

        raise Exception(f'Not implemented: {self.active_overlay_type}')

    def pad_overlay_picks(self):
        prev_overlay_ind = self.current_overlay_ind
        prev_overlay_data_ind = self.overlay_data_index
        prev_visibilities = self.overlay_visibilities
        self.restore_backup_overlay_visibilities()

        if self.current_overlay_ind == -1:
            self.next_overlay()
            self.reset_overlay_data_index_map()
            self.reset_overlay_picks()

        cur_overlay = self.active_overlay
        while cur_overlay is not None:
            self.pad_data_with_empty_lists()
            self.save_overlay_picks()
            cur_overlay = self.next_overlay()
            self.reset_overlay_data_index_map()
            self.reset_overlay_picks()

        self.current_overlay_ind = prev_overlay_ind
        self.overlay_visibilities = prev_visibilities
        if prev_overlay_data_ind != -1:
            self.reset_overlay_data_index_map()
        self.overlay_data_index = prev_overlay_data_ind
        self.reset_overlay_picks()

    def pad_data_with_empty_lists(self):
        if self.overlay_data_index == -1:
            self.overlay_data_index += 1

        # This increments the overlay data index to the end and inserts
        # empty lists along the way.
        if self.active_overlay_type == OverlayType.powder:
            while self.current_data_path is not None:
                # This will automatically insert a list for powder
                self.current_data_list
                self.overlay_data_index += 1
        elif self.active_overlay_type == OverlayType.laue:
            while self.current_data_path is not None:
                # Use NaN's to indicate a skip for laue
                self.current_data_list.append((np.nan, np.nan))
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

        if self.active_overlay_type == OverlayType.powder:
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

    def point_picked(self):
        linebuilder = self.line_picker.linebuilder
        data = (linebuilder.xs[-1], linebuilder.ys[-1])
        if self.active_overlay_type == OverlayType.powder:
            self.current_data_list.append(data)
        if self.active_overlay_type == OverlayType.laue:
            _, _, ind = self.current_data_path
            self.current_data_list[ind] = data
            self.increment_overlay_data_index()

            # In case a point was over-written, force an update of
            # the line artists.
            self.update_lines_from_picks()

    def line_completed(self):
        self.increment_overlay_data_index()

    def last_point_removed(self):
        if self.active_overlay_type == OverlayType.powder:
            if len(self.current_data_list) == 0:
                # Go back one line
                self.decrement_overlay_data_index()
            if len(self.current_data_list) == 0:
                # Still nothing to do
                return
            # Remove the last point of data
            self.current_data_list.pop(-1)
        elif self.active_overlay_type == OverlayType.laue:
            self.decrement_overlay_data_index()
            _, _, ind = self.current_data_path
            if 0 <= ind < len(self.current_data_list):
                self.current_data_list[ind] = (np.nan, np.nan)

    def hide_artists(self):
        if self.line_picker:
            self.line_picker.hide_artists()

    def show_artists(self):
        if self.line_picker:
            self.line_picker.show_artists()

    def update_current_hkl_label(self):
        if not self.line_picker or not self.active_overlay:
            return

        overlay = self.active_overlay
        path = ['data'] + list(self.current_data_path)
        path[2] = 'hkls'
        cur = overlay
        for entry in path:
            cur = cur[entry]

        hkl = hklToStr(cur)
        label = f'Current hkl:  {hkl}'
        if self.active_overlay_type == OverlayType.laue:
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
                data = ([], [])
            line.set_data(data)

        self.overlay_data_index = prev_data_index
        picker.canvas.draw_idle()
