import numpy as np

from hexrd.ui.constants import ViewType
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import update_overlay_data

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

    @property
    def all_detector_borders(self):
        # return self.pv.all_detector_borders
        # Until we compute this, just return an empty dict of detectors
        return {k: [] for k in self.instr.detectors}

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
        # update_overlay_data(self.instr, self.type)
        # FIXME stereo: no overlays yet for stereographic
        pass

    def update_detector(self, det):
        if self.project_from_polar:
            self.pv.update_detector(det)

        self.draw_stereo()
