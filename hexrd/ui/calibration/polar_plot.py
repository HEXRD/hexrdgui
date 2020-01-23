import numpy as np

from hexrd import instrument
from .polarview import PolarView

from .display_plane import DisplayPlane

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.utils import select_merged_rings


def polar_viewer():
    images_dict = HexrdConfig().current_images_dict()

    # HEDMInstrument expects None Euler angle convention for the
    # config. Let's get it as such.
    iconfig = HexrdConfig().instrument_config_none_euler_convention
    return InstrumentViewer(iconfig, images_dict)


def load_instrument(config):
    rme = HexrdConfig().rotation_matrix_euler()
    return instrument.HEDMInstrument(instrument_config=config,
                                     tilt_calibration_mapping=rme)


class InstrumentViewer:

    def __init__(self, config, images_dict):
        self.type = 'polar'
        self.instr = load_instrument(config)
        self.images_dict = images_dict
        self.dplane = DisplayPlane()

        # Resolution settings
        # As far as I can tell, self.pixel_size won't actually change
        # anything for a polar plot, so just hard-code it.
        self.pixel_size = 0.5

        self._make_dpanel()

        self.draw_polar()
        self.add_rings()

    def _make_dpanel(self):
        self.dpanel_sizes = self.dplane.panel_size(self.instr)
        self.dpanel = self.dplane.display_panel(self.dpanel_sizes,
                                                self.pixel_size)

    @property
    def angular_grid(self):
        return self.pv.angular_grid

    def draw_polar(self):
        """show polar view of rings"""
        self.pv = PolarView(self.instr, eta_min=-180., eta_max=180.)
        self.pv.warp_all_images()

        tth_min = HexrdConfig().polar_res_tth_min
        tth_max = HexrdConfig().polar_res_tth_max

        self._extent = [tth_min, tth_max, 180., -180.]   # l, r, b, t
        self.img = self.pv.img
        self.snip1d_background = self.pv.snip1d_background

    def clear_rings(self):
        self.ring_data = {}

    def generate_rings(self, plane_data):
        rings = []
        rbnds = []
        rbnd_indices = []

        selected_rings = HexrdConfig().selected_rings
        if HexrdConfig().show_rings:
            dp = self.dpanel

            if selected_rings:
                # We should only get specific values
                tth_list = plane_data.getTTh()
                tth_list = [tth_list[i] for i in selected_rings]
                delta_tth = np.degrees(plane_data.tThWidth)

                ring_angs, ring_xys = dp.make_powder_rings(
                    tth_list, delta_tth=delta_tth, delta_eta=1)
            else:
                ring_angs, ring_xys = dp.make_powder_rings(
                    plane_data, delta_eta=1)

                tth_list = plane_data.getTTh()

            for tth in np.degrees(tth_list):
                rings.append(np.array([[-180, tth], [180, tth]]))

        if HexrdConfig().show_ring_ranges:
            indices, ranges = plane_data.getMergedRanges()

            if selected_rings:
                # This ensures the correct ranges are selected
                indices, ranges = select_merged_rings(selected_rings, indices,
                                                      ranges)

            for ind, r in zip(indices, np.degrees(ranges)):
                rbnds.append(np.array([[-180, r[0]],
                                       [180, r[0]]]))
                rbnds.append(np.array([[-180, r[1]],
                                       [180, r[1]]]))
                # Append twice since we append to rbnd_data twice
                rbnd_indices.append(ind)
                rbnd_indices.append(ind)

        return rings, rbnds, rbnd_indices

    def add_rings(self):
        self.clear_rings()

        # If there are any rings selected, only do the active material
        if HexrdConfig().selected_rings or not HexrdConfig().show_all_materials:
            material_names = [HexrdConfig().active_material_name()]
        else:
            material_names = HexrdConfig().materials.keys()

        for name in material_names:
            mat = HexrdConfig().material(name)

            rings, rbnds, rbnd_indices = self.generate_rings(mat.planeData)

            self.ring_data[name] = {
                'ring_data': rings,
                'rbnd_data': rbnds,
                'rbnd_indices': rbnd_indices
            }

        return self.ring_data

    def update_detector(self, det):
        self.pv.update_detector(det)
        self.img = self.pv.img

    def write_image(self, filename='polar_image.npz'):
        np.savez(filename,
                 tth_coordinates=self.angular_grid[1],
                 eta_coordinates=self.angular_grid[0],
                 intensities=self.img,
                 extent=np.radians(self._extent))
