from itertools import chain

import numpy as np

from hexrdgui.constants import ViewType
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays import update_overlay_data


def raw_iviewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = ViewType.raw
        self.instr = create_hedm_instrument()
        self.roi_info = {}

        self.setup_roi_info()

    def update_overlay_data(self):
        update_overlay_data(self.instr, self.type)

    def update_detector(self, det):
        # First, convert to the "None" angle convention
        iconfig = HexrdConfig().instrument_config_none_euler_convention

        t_conf = iconfig['detectors'][det]['transform']
        self.instr.detectors[det].tvec = t_conf['translation']
        self.instr.detectors[det].tilt = t_conf['tilt']

        # Since these are just individual images, no further updates are needed

    @property
    def has_roi(self):
        # Assume it has ROI support if a single detector supports it
        panel = next(iter(self.instr.detectors.values()))
        return all(x is not None for x in (panel.roi, panel.group))

    @property
    def roi_groups(self):
        return self.roi_info.get('groups', {})

    @property
    def roi_stitched_shapes(self):
        return self.roi_info.get('stitched_shapes', {})

    def setup_roi_info(self):
        if not self.has_roi:
            # Required info is missing
            return

        groups = {}
        for det_key, panel in self.instr.detectors.items():
            groups.setdefault(panel.group, []).append(det_key)

        self.roi_info['groups'] = groups

        # Find the ROI bounds for each group
        stitched_shapes = {}
        for group, det_keys in groups.items():
            row_size = 0
            col_size = 0
            for det_key in det_keys:
                panel = self.instr.detectors[det_key]
                row_size = max(row_size, panel.roi[0][1])
                col_size = max(col_size, panel.roi[1][1])

            stitched_shapes[group] = (row_size, col_size)

        self.roi_info['stitched_shapes'] = stitched_shapes

    def raw_to_stitched(self, ij, det_key):
        ij = np.array(ij)

        panel = self.instr.detectors[det_key]

        if ij.size != 0:
            ij[:, 0] += panel.roi[0][0]
            ij[:, 1] += panel.roi[1][0]

        return ij, panel.group

    def stitched_to_raw(self, ij, stitched_key):
        ij = np.atleast_2d(ij)

        ret = {}
        for det_key in self.roi_groups[stitched_key]:
            panel = self.instr.detectors[det_key]
            on_panel_rows = (
                in_range(ij[:, 0], panel.roi[0]) &
                in_range(ij[:, 1], panel.roi[1])
            )
            if np.any(on_panel_rows):
                new_ij = ij[on_panel_rows]
                new_ij[:, 0] -= panel.roi[0][0]
                new_ij[:, 1] -= panel.roi[1][0]
                ret[det_key] = new_ij

        return ret

    def raw_images_to_stitched(self, group_names, images_dict):
        shapes = self.roi_stitched_shapes
        stitched = {}
        for group in group_names:
            for det_key in self.roi_groups[group]:
                panel = self.instr.detectors[det_key]
                if group not in stitched:
                    stitched[group] = np.empty(shapes[group])
                image = stitched[group]
                roi = panel.roi
                image[slice(*roi[0]), slice(*roi[1])] = images_dict[det_key]

        return stitched

    def create_overlay_data(self, overlay):
        if HexrdConfig().stitch_raw_roi_images:
            return self.create_roi_overlay_data(overlay)

        return overlay.data

    def create_roi_overlay_data(self, overlay):
        ret = {}
        for det_key, data in overlay.data.items():
            panel = self.instr.detectors[det_key]

            def raw_to_stitched(x):
                # x is in "ji" coordinates
                x[:, 0] += panel.roi[1][0]
                x[:, 1] += panel.roi[0][0]

            group = panel.group
            ret.setdefault(group, {})
            for data_key, entry in data.items():
                if data_key == overlay.ranges_indices_key:
                    # Need to adjust indices since we stack ranges
                    if data_key not in ret[group]:
                        ret[group][data_key] = entry
                        continue

                    # We need to adjust these rbnd_indices. Find the max.
                    prev_max = max(chain(*ret[group][data_key]))
                    for i, x in enumerate(entry):
                        entry[i] = [j + prev_max + 1 for j in x]
                    ret[group][data_key] += entry
                    continue

                if data_key not in overlay.plot_data_keys:
                    # This is not for plotting. No conversions needed.
                    ret[group][data_key] = entry
                    continue

                if len(entry) == 0:
                    continue

                # Points are 2D in shape, and lines are 3D in shape.
                # Perorm the conversion regardless of the dimensions.
                if isinstance(entry, list) or entry.ndim == 3:
                    for x in entry:
                        # This will convert in-place since `x` is a view
                        raw_to_stitched(x)
                else:
                    raw_to_stitched(entry)

                if data_key in ret[group]:
                    # Stack it with previous entries
                    if isinstance(ret[group][data_key], list):
                        entry = ret[group][data_key] + entry
                    else:
                        entry = np.vstack((ret[group][data_key], entry))

                ret[group][data_key] = entry

        # If data was missing for a whole group, set it to an empty list.
        for group in ret:
            for data_key in overlay.plot_data_keys:
                if data_key not in ret[group]:
                    ret[group][data_key] = []

        return ret


def in_range(x, range):
    return (range[0] <= x) & (x < range[1])
