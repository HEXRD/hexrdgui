import h5py
import os
import numpy as np

from .polarview import PolarView

from .display_plane import DisplayPlane

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui import utils


def polar_viewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = 'polar'
        self.instr = utils.create_hedm_instrument()
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
    def all_detector_borders(self):
        return self.pv.all_detector_borders

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

        # If there are no rings, there is nothing to do
        if not HexrdConfig().show_overlays or len(plane_data.getTTh()) == 0:
            return rings, rbnds, rbnd_indices

        for tth in np.degrees(plane_data.getTTh()):
            rings.append(np.array([[-180, tth], [180, tth]]))

        if plane_data.tThWidth is not None:
            indices, ranges = plane_data.getMergedRanges()

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

        for name in HexrdConfig().visible_material_names:
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
        # Prepare the data to write out
        data = {
            'tth_coordinates': self.angular_grid[1],
            'eta_coordinates': self.angular_grid[0],
            'intensities': self.img,
            'extent': np.radians(self._extent)
        }

        # Delete the file if it already exists
        if os.path.exists(filename):
            os.remove(filename)

        # Check the file extension
        _, ext = os.path.splitext(filename)
        ext = ext.lower()

        if ext == '.npz':
            # If it looks like npz, save as npz
            np.savez(filename, **data)
        else:
            # Default to HDF5 format
            f = h5py.File(filename, 'w')
            for key, value in data.items():
                f.create_dataset(key, data=value)
