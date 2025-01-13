import copy
from functools import partial
import itertools
from pathlib import Path

import h5py
import numpy as np

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox

from hexrd.fitting.calibration import LaueCalibrator, PowderCalibrator
from hexrd.instrument import unwrap_h5_to_dict
from hexrd.utils.hkl import hkl_to_str

from hexrdgui.calibration.auto import PowderCalibrationDialog
from hexrdgui.calibration.calibration_dialog import CalibrationDialog
from hexrdgui.calibration.material_calibration_dialog_callbacks import (
    format_material_params_func,
    MaterialCalibrationDialogCallbacks,
)
from hexrdgui.calibration.laue_auto_picker_dialog import LaueAutoPickerDialog
from hexrdgui.calibration.pick_based_calibration import (
    create_instrument_calibrator,
)
from hexrdgui.calibration.hkl_picks_tree_view_dialog import (
    generate_picks_results, overlays_to_tree_format, HKLPicksTreeViewDialog,
    picks_cartesian_to_angles, tree_format_to_picks,
)
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.constants import OverlayType, ViewType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.line_picker_dialog import LinePickerDialog
from hexrdgui.overlays.overlay import Overlay
from hexrdgui.progress_dialog import ProgressDialog
from hexrdgui.select_item_dialog import SelectItemDialog
from hexrdgui.utils import (
    array_index_in_list,
    masks_applied_to_panel_buffers, unique_array_list
)
from hexrdgui.utils.dicts import ndarrays_to_lists


class CalibrationRunner(QObject):

    calibration_finished = Signal()

    def __init__(self, canvas, async_runner, parent=None):
        super().__init__(parent)

        self.canvas = canvas
        self.current_overlay_ind = -1
        self.overlay_data_index = -1

        self.line_picker = None
        self.overlay_picks = {}

        self.async_runner = async_runner
        self.parent = parent

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

    def enable_focus_mode(self, b):
        # FIXME: We must avoid using focus mode until we can be sure
        # that this issue will not happen again:
        # https://github.com/HEXRD/hexrdgui/issues/1556
        # We *cannot* allow the GUI to remain disabled after calibration.

        # HexrdConfig().enable_canvas_focus_mode.emit(b)
        # HexrdConfig().enable_canvas_toolbar.emit(not b)
        pass

    def clear_all_overlay_picks(self):
        for overlay in self.active_overlays:
            overlay.reset_calibration_picks()
            overlay.pad_picks_data()

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
        if not dialog.exec():
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
        overlay.pad_picks_data()

        title = overlay.name

        if overlay.xray_source is not None and overlay.xray_source != HexrdConfig().active_beam_name:
            self.switch_xray_source(overlay.xray_source)

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

        if overlay.is_laue:
            # Set the line settings to use a circle
            kwargs['line_settings'] = {
                'marker': 'o',
                'fillstyle': 'none',
                'markersize': 8,
                'markeredgewidth': 2,
                'linewidth': 0,
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

    def switch_xray_source(self, xray_source: str):
        # Update the polar view to use this xrs source
        HexrdConfig().active_beam_name = xray_source

        if self.line_picker is not None:
            if self.line_picker.zoom_canvas is not None:
                self.line_picker.zoom_canvas.skip_next_render = True

        # Wait until canvas finishes updating
        progress_dialog = ProgressDialog(self.canvas)
        progress_dialog.setRange(0, 0)
        progress_dialog.setWindowTitle(
            f'Switching beam to {xray_source}'
        )
        progress_dialog.show()
        while self.canvas.iviewer is None:
            # We must process events so that when the polar view has been
            # generated again, it can set the iviewer on the canvas.
            QCoreApplication.processEvents()

        progress_dialog.hide()

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

        results = {overlay.name: cart[overlay.name]}

        # Convert to angles, and to lists
        results = picks_cartesian_to_angles(results)
        ndarrays_to_lists(results)

        # Set the new picks on the overlay
        updated_picks = tree_format_to_picks(self.overlays, results)
        overlay.calibration_picks_polar = updated_picks[0]['picks']
        overlay.pad_picks_data()
        self.reset_overlay_picks()

        dialog = self.view_picks_table()

        def on_rejected():
            dialog.tree_view.clear_artists()
            self.pick_this_line()

        dialog.ui.accepted.connect(self.finish_line)
        dialog.ui.rejected.connect(on_rejected)

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
        dialog.button_box_visible = True
        dialog.ui.show()

        kwargs = {
            'dialog': dialog,
            'highlighting': highlighting,
            'prev_visibilities': prev_visibilities,
        }

        # We need to ensure the finished func is called before any
        # accepted/rejected connections are called. finished() is
        # normally called after accepted/rejected, so we will connect
        # to accepted/rejected directly.
        dialog.ui.accepted.connect(
            partial(self.view_picks_finished, accepted=True, **kwargs))
        dialog.ui.rejected.connect(
            partial(self.view_picks_finished, accepted=False, **kwargs))

        # Make sure focus mode is enabled while viewing the picks
        self.enable_focus_mode(True)

        return dialog

    def view_picks_finished(self, accepted, dialog, highlighting,
                            prev_visibilities):
        # Turn off focus mode (which may be turned back on if the line picker
        # will reappear)
        self.enable_focus_mode(False)

        if accepted:
            # Update all of the picks with the modified data
            updated_picks = tree_format_to_picks(
                self.overlays,
                dialog.dictionary,
            )
            for i, new_picks in enumerate(updated_picks):
                self.active_overlays[i].calibration_picks_polar = (
                    new_picks['picks']
                )

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

        # Updating the overlays no longer calls draw_idle(), so we need
        # to do so now. Maybe we should change the line picker so that
        # picked points are animated too...
        self.canvas.draw_idle()

    def finish_line(self):
        self.save_overlay_picks()
        self.pick_next_line()

    def generate_picks_results(self, polar=True):
        return generate_picks_results(self.active_overlays, polar=polar)

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

    def finish(self):
        # Ensure the line picker is disabled and gone
        self.disable_line_picker()
        self.line_picker = None
        self.show_calibration_dialog()

    def show_calibration_dialog(self):
        # These picks need to be in cartesian
        picks = self.generate_picks_results(polar=False)
        materials = self.pick_materials
        instr = create_hedm_instrument()
        # Set this for the default calibration flags we will use
        instr.calibration_flags = (
            HexrdConfig().get_statuses_instrument_format()
        )

        img_dict = HexrdConfig().masked_images_dict

        self.ic = create_instrument_calibrator(
            picks, instr, img_dict, materials
        )

        format_extra_params_func = partial(
            format_material_params_func,
            overlays=self.active_overlays,
            calibrators=self.ic.calibrators,
        )

        # Now show the calibration dialog
        kwargs = {
            'instr': instr,
            'params_dict': self.ic.params,
            'format_extra_params_func': format_extra_params_func,
            'parent': self.parent,
            'engineering_constraints': self.ic.engineering_constraints,
            'window_title': 'Composite Calibration',
            'help_url': 'calibration/composite_laue_and_powder',
        }
        dialog = CalibrationDialog(**kwargs)

        # Connect interactions to functions
        self._dialog_callback_handler = CalibrationCallbacks(
            self.active_overlays,
            dialog,
            self.ic,
            instr,
            self.async_runner,
        )
        self._dialog_callback_handler.instrument_updated.connect(
            self.on_calibration_finished)
        dialog.show()

        self._calibration_dialog = dialog

        return dialog

    def on_calibration_finished(self):
        overlays = self.active_overlays
        for overlay, calibrator in zip(overlays, self.ic.calibrators):
            modified = any(
                self.ic.params[param_name].vary
                for param_name in calibrator.param_names
            )
            if not modified:
                # Just skip over it
                continue

            if calibrator.type == 'laue':
                overlay.crystal_params = calibrator.grain_params

            mat_name = overlay.material_name
            HexrdConfig().flag_overlay_updates_for_material(mat_name)
            HexrdConfig().material_modified.emit(mat_name)

        # In case any overlays changed
        HexrdConfig().overlay_config_changed.emit()
        HexrdConfig().update_overlay_editor.emit()
        self.calibration_finished.emit()

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

    @property
    def overlay_picks_with_hkls(self):
        # Add the hkls before returning
        with_hkls = {}
        for det_key, hkls in self.active_overlay.hkls.items():
            with_hkls[det_key] = {}
            for i, hkl in enumerate(hkls):
                hkl_str = hkl_to_str(hkl)
                with_hkls[det_key][hkl_str] = self.overlay_picks[det_key][i]

        return with_hkls

    @overlay_picks_with_hkls.setter
    def overlay_picks_with_hkls(self, v):
        # Remove the hkls before setting to `self.overlay_picks`
        without_hkls = {}
        for det_key, hkls in self.active_overlay.hkls.items():
            without_hkls[det_key] = []
            for hkl in hkls:
                hkl_str = hkl_to_str(hkl)
                if det_key not in v or hkl_str not in v[det_key]:
                    without_hkls[det_key].append([])
                else:
                    without_hkls[det_key].append(v[det_key][hkl_str])

        self.overlay_picks = without_hkls

    def reset_overlay_picks(self):
        calibration_picks = self.active_overlay.calibration_picks_polar
        self.overlay_picks_with_hkls = copy.deepcopy(calibration_picks)

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

                    tth_values = data[key][data_key][hkl_index][:, 0]
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
                    min_eta_values[key] = np.nanmin(rings[hkl_index][:, 1])
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
            self.overlay_picks_with_hkls)

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
                root_list.append([np.nan, np.nan])

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
                self.current_data_list[ind] = [np.nan, np.nan]

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

        hkl = hkl_to_str(cur)
        label = f'Current hkl:  {hkl}'
        if overlay.is_laue:
            data_list = self.current_data_list
            if self.overlay_data_index < len(data_list):
                data_entry = data_list[self.overlay_data_index]
                if not any(np.isnan(x) for x in data_entry):
                    label += '  (overwriting)'

        self.line_picker.current_pick_label = label

    def update_lines_from_picks(self):
        if not self.line_picker or not self.line_picker.lines:
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
        overlay.pad_picks_data()
        return funcs[overlay.type]()

    def auto_pick_powder_points(self):
        overlay = self.active_overlay
        material = overlay.material
        dialog = PowderCalibrationDialog(material, self.canvas)
        if not dialog.exec():
            # User canceled
            self.restore_state()
            return

        # The options they chose are saved here
        options = HexrdConfig().config['calibration']['powder']
        self.instr = create_hedm_instrument()

        if options['auto_guess_initial_fwhm']:
            fwhm_estimate = None
        else:
            fwhm_estimate = options['initial_fwhm']

        kwargs = {
            'instr': self.instr,
            'material': material,
            'img_dict': HexrdConfig().masked_images_dict,
            'eta_tol': options['eta_tol'],
            'fwhm_estimate': fwhm_estimate,
            'pktype': options['pk_type'],
            'bgtype': options['bg_type'],
            'tth_distortion': overlay.tth_distortion_dict,
            'xray_source': overlay.xray_source,
        }

        self.auto_pc = PowderCalibrator(**kwargs)
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
            # This will save the results on the laue_auto_picker
            self.auto_pc.autopick_points(**kwargs)

        # Convert to calibration picks
        return self.auto_pc.calibration_picks

    def auto_powder_pick_finished(self, auto_picks):
        self.active_overlay.calibration_picks = auto_picks
        self.reset_overlay_picks()

        # View the picks and ask the user to accept them
        dialog = self.view_picks_table()

        def on_rejected():
            dialog.tree_view.clear_artists()
            self.pick_this_line()

        dialog.ui.accepted.connect(self.finish_line)
        dialog.ui.rejected.connect(on_rejected)

    def auto_pick_laue_points(self):
        overlay = self.active_overlay
        dialog = LaueAutoPickerDialog(overlay, self.canvas)
        if not dialog.exec():
            # User canceled
            self.restore_state()
            return

        self.instr = create_hedm_instrument()

        init_kwargs = {
            'instr': self.instr,
            'material': overlay.material,
            'grain_params': overlay.crystal_params,
            'min_energy': overlay.min_energy,
            'max_energy': overlay.max_energy,
            'euler_convention': HexrdConfig().euler_angle_convention,
            'xray_source': overlay.xray_source,
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
            # This will save the results on the laue_auto_picker
            self.laue_auto_picker.autopick_points(**kwargs)

        # Convert to calibration picks
        return self.laue_auto_picker.calibration_picks

    def auto_laue_pick_finished(self, auto_picks):
        self.active_overlay.calibration_picks = auto_picks
        self.active_overlay.pad_picks_data()

        # Save these picks to self as well
        self.reset_overlay_picks()

        # View the picks and ask the user to accept them
        dialog = self.view_picks_table()

        def on_rejected():
            dialog.tree_view.clear_artists()
            self.pick_this_line()

        dialog.ui.accepted.connect(self.finish_line)
        dialog.ui.rejected.connect(on_rejected)


class CalibrationCallbacks(MaterialCalibrationDialogCallbacks):

    def __init__(self, overlays, *args, **kwargs):
        self.overlays = overlays

        # Use the hkl picks tree view dialog for drawing picks
        self.edit_picks_dialog = self.create_hkl_picks_tree_view_dialog()

        super().__init__(overlays, *args, **kwargs)

    def draw_picks_on_canvas(self):
        self.update_edit_picks_dictionary()
        tree_view = self.edit_picks_dialog.tree_view

        if (
            HexrdConfig().has_multi_xrs and
            not self.showing_picks_from_all_xray_sources
        ):
            skip_items = []
            for item in tree_view.model().root_item.child_items:
                overlay_name = item.data(0)
                overlay = Overlay.from_name(overlay_name)

                if overlay.xray_source != HexrdConfig().active_beam_name:
                    skip_items.append(item)

            tree_view.skip_pick_item_list = skip_items

        # Make sure these are set
        tree_view.clear_selection()
        tree_view.clear_highlights()
        tree_view.show_all_picks = True

        tree_view.draw_picks()

    def clear_drawn_picks(self):
        self.edit_picks_dialog.tree_view.clear_artists()

    def on_edit_picks_clicked(self):
        dialog = self.edit_picks_dialog
        tree_view = dialog.tree_view
        model = tree_view.model()
        model.disabled_paths.clear()

        dialog.button_box_visible = True

        def on_finished():
            self.dialog.show()
            self.redraw_picks()

        dialog.ui.accepted.connect(self.on_edit_picks_accepted)
        dialog.ui.finished.connect(on_finished)

        self.draw_picks_on_canvas()
        self.dialog.hide()

        # After the tree view is updated, disable paths that
        # don't match this XRS.
        if (
            HexrdConfig().has_multi_xrs and
            not self.showing_picks_from_all_xray_sources
        ):
            # Disable paths that don't match this XRS
            for item in model.root_item.child_items:
                overlay_name = item.data(0)
                overlay = Overlay.from_name(overlay_name)

                if overlay.xray_source != HexrdConfig().active_beam_name:
                    model.disabled_paths.append((overlay_name,))

            tree_view.collapse_disabled_paths()

        dialog.ui.show()

    def save_picks_to_file(self, selected_file):
        # Reuse the same logic from the HKLPicksTreeViewDialog
        self.edit_picks_dialog.export_picks(selected_file)

    def load_picks_from_file(self, selected_file):
        # Reuse the same logic from the HKLPicksTreeViewDialog
        dialog = self.edit_picks_dialog
        dialog.import_picks(selected_file)
        return dialog.dictionary
