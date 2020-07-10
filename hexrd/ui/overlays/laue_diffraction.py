import numpy as np

from hexrd import constants


class LaueSpotOverlay:
    def __init__(self, plane_data, instr,
                 crystal_params=None, sample_rmat=None,
                 min_energy=5., max_energy=35.,
                 tth_width=None, eta_width=None):
        self._plane_data = plane_data
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

    def overlay(self, display_mode='raw'):
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
            xy_det, hkls_in, angles, dspacing, energy = psim
            idx = ~np.isnan(energy)
            if display_mode == 'polar':
                spots = np.degrees(angles[idx, :])
                point_groups[det_key]['spots'] = spots
                point_groups[det_key]['ranges'] = self.polar_ranges(spots)
            elif display_mode in ['raw', 'cartesian']:
                panel = self.instrument.detectors[det_key]

                data = xy_det[idx, :]
                if display_mode == 'raw':
                    # Convert to pixel coordinates
                    data = panel.cartToPixel(data)
                    # Swap x and y, they are flipped
                    data[:, [0, 1]] = data[:, [1, 0]]

                point_groups[det_key]['spots'] = data
        return point_groups

    def polar_ranges(self, spots):
        # spots should be in degrees
        if not self.widths_enabled:
            return []

        widths = np.degrees([self.tth_width, self.eta_width])
        ranges = []
        for spot in spots:
            corners = [
               (spot[0] + widths[0], spot[1] + widths[1]),
               (spot[0] + widths[0], spot[1] - widths[1]),
               (spot[0] - widths[0], spot[1] - widths[1]),
               (spot[0] - widths[0], spot[1] + widths[1])
            ]
            # Put the first point at the end to complete the square
            corners.append(corners[0])
            ranges.append(corners)
        return ranges
