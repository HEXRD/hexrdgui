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

        all_tths = plane_data.getTTh()
        rings_to_use = HexrdConfig().selected_rings
        if not rings_to_use:
            # If it's empty, select all rings
            rings_to_use = list(range(len(all_tths)))

        if HexrdConfig().show_rings:
            dp = self.dpanel

            # Update the tth list with the rings to use
            tth_list = [all_tths[i] for i in rings_to_use]

            for tth in np.degrees(tth_list):
                rings.append(np.array([[-180, tth], [180, tth]]))

        if HexrdConfig().show_ring_ranges:
            indices, ranges = plane_data.getMergedRanges()

            # This ensures the correct ranges are selected
            indices, ranges = select_merged_rings(rings_to_use, indices,
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

        materials_list = HexrdConfig().visible_material_names
        if HexrdConfig().selected_rings:
            # Only show the active material, if it is part of the list
            active = HexrdConfig().active_material_name
            materials_list = [active] if active in materials_list else []

        for name in materials_list:
            mat = HexrdConfig().material(name)

            if not mat:
                # Print a warning, as this shouldn't happen
                print('Warning in InstrumentViewer.add_rings():',
                      name, 'is not a valid material')
                continue

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
