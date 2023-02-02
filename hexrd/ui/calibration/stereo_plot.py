import numpy as np

from hexrd import constants as ct
from hexrd.transforms.xfcapi import detectorXYToGvec

from hexrd.ui.constants import ViewType
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import update_overlay_data
from hexrd.ui.utils.conversions import angles_to_stereo

from .polarview import PolarView
from .stereo_project import stereo_project, stereo_projection_of_polar_view


def stereo_viewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = ViewType.stereo
        self.instr = create_hedm_instrument()

        self.pv = None

        self.draw_stereo()

    @property
    def extent(self):
        return [0, self.stereo_size, self.stereo_size, 0]

    @property
    def raw_img_dict(self):
        return HexrdConfig().masked_images_dict

    @property
    def stereo_size(self):
        return HexrdConfig().stereo_size

    @property
    def project_from_polar(self):
        return HexrdConfig().stereo_project_from_polar

    def detector_borders(self, det):
        panel = self.instr.detectors[det]

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
            angles, _ = detectorXYToGvec(
                border, panel.rmat, ct.identity_3x3,
                panel.tvec, ct.zeros_3, ct.zeros_3,
                beamVec=panel.bvec, etaVec=panel.evec)
            angles = np.asarray(angles)

            # Swap positions of tth and eta
            angles[:, [0, 1]] = angles[:, [1, 0]]

            # Need to transpose angles before and after
            borders[i] = angles_to_stereo(angles.T, self.instr,
                                          self.stereo_size).T

        return borders

    @property
    def all_detector_borders(self):
        borders = {}
        for key in self.instr.detectors:
            borders[key] = self.detector_borders(key)

        return borders

    def draw_stereo(self):
        if self.project_from_polar:
            self.draw_stereo_from_polar()
        else:
            self.draw_stereo_from_raw()

    def draw_stereo_from_raw(self):
        self.img = stereo_project(**{
            'instr': self.instr,
            'raw': self.raw_img_dict,
            'stereo_size': self.stereo_size,
        })

    def draw_stereo_from_polar(self):
        # FIXME stereo: sometimes, some instrument settings are modified that
        # should cause the polar view to be regenerated here, but it is not
        # regenerated. We should perform some checks/memoization.
        if self.pv is None:
            # Don't redraw the polar view unless we have to
            self.draw_polar()

        polar_img = self.pv.img

        tth_grid = np.degrees(self.pv.angular_grid[1][0, :])
        eta_grid = np.degrees(self.pv.angular_grid[0][:, 0])

        # Make eta between 0 and 360
        eta_grid = np.mod(eta_grid, 360)
        idx = np.argsort(eta_grid)
        eta_grid = eta_grid[idx]
        polar_img = polar_img[idx, :]

        self.img = stereo_projection_of_polar_view(**{
            'pvarray': polar_img,
            'tth_grid': tth_grid,
            'eta_grid': eta_grid,
            'instr': self.instr,
            'stereo_size': self.stereo_size,
        })

    def draw_polar(self):
        self.pv = PolarView(self.instr)
        self.pv.warp_all_images()

    def update_overlay_data(self):
        update_overlay_data(self.instr, self.type)

    def update_detector(self, det):
        if self.project_from_polar:
            self.pv.update_detector(det)

        self.draw_stereo()
