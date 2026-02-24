from __future__ import annotations

from typing import Any, Sequence, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from hexrd.instrument import HEDMInstrument

from hexrd.transforms import xfcapi
from hexrd import instrument

tvec_DFLT = np.r_[0.0, 0.0, -1000.0]
tilt_DFTL = np.zeros(3)


class DisplayPlane:

    def __init__(
        self,
        tilt: np.ndarray = tilt_DFTL,
        tvec: np.ndarray = tvec_DFLT,
    ) -> None:
        self.tilt = tilt
        self.rmat = xfcapi.make_detector_rmat(self.tilt)
        self.tvec = tvec

    def panel_size(self, instr: HEDMInstrument) -> tuple[float, float]:
        """return bounding box of instrument panels in display plane"""
        xmin_i = ymin_i = np.inf
        xmax_i = ymax_i = -np.inf
        for detector_id in instr._detectors:
            panel = instr._detectors[detector_id]
            # find max extent
            corners = np.vstack(
                [
                    panel.corner_ll,
                    panel.corner_lr,
                    panel.corner_ur,
                    panel.corner_ul,
                ]
            )
            tmp = panel.map_to_plane(corners, self.rmat, self.tvec)
            xmin, xmax = np.sort(tmp[:, 0])[[0, -1]]
            ymin, ymax = np.sort(tmp[:, 1])[[0, -1]]

            xmin_i = min(xmin, xmin_i)
            ymin_i = min(ymin, ymin_i)
            xmax_i = max(xmax, xmax_i)
            ymax_i = max(ymax, ymax_i)
            pass

        del_x = 2 * max(abs(xmin_i), abs(xmax_i))
        del_y = 2 * max(abs(ymin_i), abs(ymax_i))

        return (del_x, del_y)

    def display_panel(
        self,
        sizes: Sequence[int],
        mps: float,
        bvec: Any = None,
        xrs_dist: Any = None,
    ) -> Any:

        del_x = sizes[0]
        del_y = sizes[1]

        ncols_map = int(del_x / mps)
        nrows_map = int(del_y / mps)

        display_panel = instrument.PlanarDetector(
            rows=nrows_map,
            cols=ncols_map,
            pixel_size=(mps, mps),
            tvec=self.tvec,
            tilt=self.tilt,
            bvec=bvec,
            xrs_dist=xrs_dist,
        )

        return display_panel
