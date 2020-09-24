import numpy as np

from hexrd.ui.constants import OverlayType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.line_picker_dialog import LinePickerDialog


class CalibrationRunner:
    def __init__(self, canvas, parent=None):
        self.canvas = canvas
        self.parent = parent
        self.current_overlay_ind = -1
        self.all_overlay_picks = {}

    def run(self):
        self.validate()
        self.clear_all_overlay_picks()
        self.pick_next_line()

    def validate(self):
        # Do a quick check for refinable paramters, which are required
        flags = HexrdConfig().get_statuses_instrument_format()
        if np.count_nonzero(flags) == 0:
            raise Exception('There are no refinable parameters')

        visible_overlays = self.visible_overlays
        if not visible_overlays:
            raise Exception('No visible overlays')

        if not all(self.has_widths(x) for x in visible_overlays):
            raise Exception('All visible overlays must have widths')

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

        self._calibration_line_picker = LinePickerDialog(**kwargs)
        self._calibration_line_picker.ui.setWindowTitle(title)
        self._calibration_line_picker.start()
        self._calibration_line_picker.point_picked.connect(
            self.point_picked)
        self._calibration_line_picker.line_completed.connect(
            self.line_completed)
        self._calibration_line_picker.finished.connect(
            self.restore_backup_overlay_visibilities)
        self._calibration_line_picker.finished.connect(
            self.remove_all_highlighting)
        self._calibration_line_picker.result.connect(self.finish_line)

    def finish_line(self):
        self.save_overlay_picks()
        self.pick_next_line()

    def finish(self):
        print(f'{self.all_overlay_picks=}')

    def set_exclusive_overlay_visibility(self, overlay):
        self.overlay_visibilities = [overlay is x for x in self.overlays]

    def restore_backup_overlay_visibilities(self):
        self.overlay_visibilities = self.backup_overlay_visibilities
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
        self.overlay_picks = {}

    def reset_overlay_data_index_map(self):
        self.overlay_data_index = -1

        if self.active_overlay_type == OverlayType.powder:
            data_key = 'rings'
        elif self.active_overlay_type == OverlayType.laue:
            data_key = 'spots'
        else:
            raise Exception(f'{self.active_overlay_type} not implemented')

        data_map = {}
        ind = 0
        for key, value in self.active_overlay['data'].items():
            for i in range(len(value[data_key])):
                data_map[ind] = (key, data_key, i)
                ind += 1

        self.overlay_data_index_map = data_map

    def save_overlay_picks(self):
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
            return root_list

        raise Exception(f'Not implemented: {self.active_overlay_type}')

    def increment_overlay_data_index(self):
        self.overlay_data_index += 1
        data_path = self.current_data_path
        if data_path is None:
            # We are done picking for this overlay.
            if hasattr(self, '_calibration_line_picker'):
                self._calibration_line_picker.ui.accept()
            return

        self.active_overlay['highlights'] = [data_path]
        HexrdConfig().flag_overlay_updates_for_all_materials()
        HexrdConfig().overlay_config_changed.emit()

    def point_picked(self):
        linebuilder = self._calibration_line_picker.linebuilder
        data = (linebuilder.xs[-1], linebuilder.ys[-1])
        self.current_data_list.append(data)
        if self.active_overlay_type == OverlayType.laue:
            self.increment_overlay_data_index()

    def line_completed(self):
        self.increment_overlay_data_index()
