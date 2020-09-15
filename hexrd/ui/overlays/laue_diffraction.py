import copy

import numpy as np

from hexrd import constants
from hexrd.transforms import xfcapi

from hexrd.ui.constants import ViewType


class LaueSpotOverlay:
    def __init__(self, plane_data, instr,
                 crystal_params=None, sample_rmat=None,
                 min_energy=5., max_energy=35.,
                 tth_width=None, eta_width=None):
        self.plane_data = plane_data
        self._instrument = instr
        if crystal_params is None:
            self._crystal_params = np.hstack(
                [constants.zeros_3,
                 constants.zeros_3,
                 constants.identity_6x1]
            )
        else:
            self.crystal_params = crystal_params

        self._min_energy = min_energy
        self._max_energy = max_energy
        if sample_rmat is None:
            self._sample_rmat = constants.identity_3x3
        else:
            self.sample_rmat = sample_rmat

        self.tth_width = tth_width
        self.eta_width = eta_width

    @property
    def plane_data(self):
        return self._plane_data

    @plane_data.setter
    def plane_data(self, v):
        self._plane_data = v
        # For Laue overlays, we will use all hkl values
        if self._plane_data.exclusions is not None:
            self._plane_data = copy.deepcopy(self._plane_data)
            self._plane_data.exclusions = None

    @property
    def instrument(self):
        return self._instrument

    @property
    def crystal_params(self):
        return self._crystal_params

    @crystal_params.setter
    def crystal_params(self, x):
        assert len(x) == 12, 'input must be array-like with length 12'
        self._crystal_params = np.array(x)

    @property
    def min_energy(self):
        return self._min_energy

    @min_energy.setter
    def min_energy(self, x):
        assert x < self.max_energy
        self._min_energy = x

    @property
    def max_energy(self):
        return self._max_energy

    @max_energy.setter
    def max_energy(self, x):
        assert x > self.min_energy
        self._max_energy = x

    @property
    def sample_rmat(self):
        return self._sample_rmat

    @sample_rmat.setter
    def sample_rmat(self, x):
        assert isinstance(x, np.ndarray), 'input must be a (3, 3) array'
        self._sample_rmat = x

    @property
    def widths_enabled(self):
        widths = ['tth_width', 'eta_width']
        return all(getattr(self, x) is not None for x in widths)

    def overlay(self, display_mode=ViewType.raw):
        sim_data = self.instrument.simulate_laue_pattern(
            self.plane_data,
            minEnergy=self.min_energy,
            maxEnergy=self.max_energy,
            rmat_s=self.sample_rmat,
            grain_params=[self.crystal_params, ])

        point_groups = {}
        keys = ['spots', 'ranges']
        for det_key, psim in sim_data.items():
            point_groups[det_key] = {key: [] for key in keys}

            # grab panel and split out simulation results
            # !!! note that the sim results are lists over number of grains
            #     and here we explicitly have one.
            panel = self.instrument.detectors[det_key]
            xy_det, hkls_in, angles, dspacing, energy = psim

            # find valid points
            idx = ~np.isnan(energy[0])  # there is only one grain here

            # filter (tth, eta) results
            xy_data = xy_det[0][idx, :]
            angles = angles[0][idx, :]  # these are in radians

            # !!! apply offset corrections to angles
            # convert to angles in LAB ref
            angles_corr, _ = xfcapi.detectorXYToGvec(
                xy_data, panel.rmat, self.sample_rmat,
                panel.tvec, constants.zeros_3, constants.zeros_3,
                beamVec=self.instrument.beam_vector,
                etaVec=self.instrument.eta_vector
            )
            angles_corr = np.vstack(angles_corr).T
            if display_mode == ViewType.polar:
                range_corners = self.range_corners(angles_corr)
                point_groups[det_key]['spots'] = np.degrees(angles_corr)
                point_groups[det_key]['ranges'] = np.degrees(range_corners)
            elif display_mode in [ViewType.raw, ViewType.cartesian]:
                # !!! verify this
                range_corners = self.range_corners(angles)
                panel = self.instrument.detectors[det_key]
                data = xy_data
                if display_mode == ViewType.raw:
                    # Convert to pixel coordinates
                    data = panel.cartToPixel(data)
                    # Swap x and y, they are flipped
                    data[:, [0, 1]] = data[:, [1, 0]]

                point_groups[det_key]['spots'] = data
                point_groups[det_key]['ranges'] = self.range_data(
                    range_corners, display_mode, panel
                )

        return point_groups

    def range_corners(self, spots):
        # spots should be in degrees
        if not self.widths_enabled:
            return []

        widths = (self.tth_width, self.eta_width)
        tol_box = np.array(
            [[0.5, 0.5],
             [0.5, -0.5],
             [-0.5, -0.5],
             [-0.5, 0.5]]
        )
        ranges = []
        for spot in spots:
            corners = np.tile(spot, (4, 1)) + tol_box*np.tile(widths, (4, 1))
            # Put the first point at the end to complete the square
            corners.append(corners[0])
            ranges.append(corners)

        return ranges

    @property
    def tvec_c(self):
        if self.crystal_params is None:
            return None
        return self.crystal_params[3:6].reshape(3, 1)

    def range_data(self, range_corners, display_mode, panel):
        # This function is only for raw and cartesian views
        if not range_corners:
            return []

        tvec_c = self.tvec_c

        # The range data is curved for raw and cartesian.
        # Get more intermediate points so the data reflects this.
        results = []
        for corners in range_corners:
            data = []
            for i in range(len(corners) - 1):
                tmp = np.linspace(corners[i], corners[i + 1])
                data.extend(panel.angles_to_cart(tmp, tvec_c=tvec_c))

            data = np.array(data)
            if display_mode == ViewType.raw:
                data = panel.cartToPixel(data)
                data[:, [0, 1]] = data[:, [1, 0]]

            results.append(data)

        return results
