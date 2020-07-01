import h5py
import os
import numpy as np

from .polarview import PolarView

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import PowderLineOverlay


def polar_viewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = 'polar'
        self.instr = create_hedm_instrument()
        self.images_dict = HexrdConfig().current_images_dict()

        # Resolution settings
        # As far as I can tell, self.pixel_size won't actually change
        # anything for a polar plot, so just hard-code it.
        self.pixel_size = 0.5

        self.draw_polar()
        self.add_rings()

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

    def add_rings(self):
        self.clear_rings()

        for name in HexrdConfig().visible_material_names:
            mat = HexrdConfig().material(name)

            if not mat:
                # Print a warning, as this shouldn't happen
                print('Warning in InstrumentViewer.add_rings():',
                      name, 'is not a valid material')
                continue

            overlay = PowderLineOverlay(mat.planeData, self.instr)
            self.ring_data[name] = overlay.overlay('polar')

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
