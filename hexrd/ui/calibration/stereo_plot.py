from pathlib import Path

import h5py
import numpy as np
from hexrd import constants as ct
from hexrd.rotations import mapAngle

from hexrd.ui.constants import ViewType
from hexrd.ui.create_hedm_instrument import (
    create_hedm_instrument, create_view_hedm_instrument
)
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import update_overlay_data
from hexrd.ui.utils.conversions import angles_to_stereo, cart_to_angles

from .polarview import PolarView
from .stereo_project import stereo_project, stereo_projection_of_polar_view


def stereo_viewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = ViewType.stereo

        # This instrument is used to generate the overlays and other things
        self.instr = create_hedm_instrument()

        # This instrument has a VISAR view and is used to generate the image
        self.instr_pv = create_view_hedm_instrument()
        self.pv = None
        self.img = None

        self.draw_stereo()

    @property
    def extent(self):
        return [0, self.stereo_size, 0, self.stereo_size]

    @property
    def raw_img_dict(self):
        return HexrdConfig().create_masked_images_dict()

    @property
    def stereo_size(self):
        return HexrdConfig().stereo_size

    @property
    def eta_period(self):
        return HexrdConfig().polar_res_eta_period

    @property
    def project_from_polar(self):
        return HexrdConfig().stereo_project_from_polar

    def detector_borders(self, det):
        panel = self.instr_pv.detectors[det]

        # First, create the polar view version of the borders
        # (this skips some things like trimming based upon tth/eta min/max)
        row_vec, col_vec = panel.row_pixel_vec, panel.col_pixel_vec
        x_start, x_stop = col_vec[0], col_vec[-1]
        y_start, y_stop = row_vec[0], row_vec[-1]

        # Create the borders in Cartesian
        borders = [
            [[x, y_start] for x in col_vec],
            [[x, y_stop] for x in col_vec],
            [[x_start, y] for y in row_vec],
            [[x_stop, y] for y in row_vec]
        ]

        # Convert each border to angles, then stereo
        for i, border in enumerate(borders):
            angles = np.radians(cart_to_angles(border, panel, self.eta_period))
            borders[i] = angles_to_stereo(angles, self.instr_pv,
                                          self.stereo_size).T

        return borders

    @property
    def all_detector_borders(self):
        borders = {}
        for key in self.instr_pv.detectors:
            borders[key] = self.detector_borders(key)

        return borders

    def draw_stereo(self):
        if self.project_from_polar:
            self.draw_stereo_from_polar()
        else:
            self.draw_stereo_from_raw()

        self.fill_image_with_nans()

    def draw_stereo_from_raw(self):
        self.img = stereo_project(**{
            'instr': self.instr_pv,
            'raw': self.raw_img_dict,
            'stereo_size': self.stereo_size,
        })

    def prep_eta_grid(self, eta_grid):
        """
        this function formats the eta grid in a
        range such that
        """
        eta_grid = mapAngle(eta_grid, (0, 360.0), units='degrees')
        idx = np.argsort(eta_grid)
        eta_grid = eta_grid[idx]

        mask = np.zeros(eta_grid.shape, dtype=bool)
        eta_grid, iduq = np.unique(eta_grid, return_index=True)
        mask[iduq] = True
        return eta_grid, idx, mask

    def pad_etas_pvarray(self, eta_grid, polar_img):
        start = np.array([eta_grid[-1] - 360])
        end = np.array([360 + eta_grid[0]])
        eta_grid = np.concatenate((start, eta_grid, end))

        pstart = np.atleast_2d(polar_img[-1, :])
        pstop = np.atleast_2d(polar_img[0, :])
        polar_img = np.vstack((pstart, polar_img, pstop))
        return eta_grid, polar_img

    def draw_stereo_from_polar(self):
        # We need to make sure `self.pv` is always updated when it needs
        # to be. But that can be done elsewhere.
        if self.pv is None:
            # Don't redraw the polar view unless we have to
            self.draw_polar()

        polar_img = self.pv.img

        extent = np.degrees(self.pv.extent)
        tth_range = extent[:2]
        eta_range = np.sort(extent[2:])

        tth_grid = np.linspace(*tth_range, polar_img.shape[1])
        eta_grid = np.linspace(*eta_range, polar_img.shape[0])

        eta_grid, idx, mask = self.prep_eta_grid(eta_grid)

        polar_img = polar_img[idx, :]
        polar_img = polar_img[mask, :]

        eta_grid, polar_img = self.pad_etas_pvarray(eta_grid, polar_img)

        self.img = stereo_projection_of_polar_view(**{
            'pvarray': polar_img,
            'tth_grid': tth_grid,
            'eta_grid': eta_grid,
            'instr': self.instr_pv,
            'stereo_size': self.stereo_size,
        })

    def draw_polar(self):
        self.pv = PolarView(self.instr_pv, distortion_instrument=self.instr)
        self.pv.warp_all_images()

    def reapply_masks(self):
        if not self.pv or not self.project_from_polar:
            return

        self.pv.reapply_masks()
        self.draw_stereo()

    def fill_image_with_nans(self):
        # If the image is a masked array, fill it with nans
        if isinstance(self.img, np.ma.masked_array):
            self.img = self.img.filled(np.nan)

    def update_overlay_data(self):
        update_overlay_data(self.instr, self.type)

    def update_detector(self, det):
        if self.project_from_polar:
            self.pv.update_detector(det)

        self.draw_stereo()

    def write_image(self, filename):
        filename = Path(filename)

        # Prepare the data to write out
        data = {
            'intensities': self.img,
        }

        # Delete the file if it already exists
        if filename.exists():
            filename.unlink()

        # Check the file extension
        ext = filename.suffix.lower()

        if ext == '.npz':
            # If it looks like npz, save as npz
            np.savez(filename, **data)
        else:
            # Default to HDF5 format
            with h5py.File(filename, 'w') as f:
                for key, value in data.items():
                    f.create_dataset(key, data=value)
