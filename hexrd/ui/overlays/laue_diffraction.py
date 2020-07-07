import numpy as np

from hexrd import constants


class LaueSpotOverlay(object):
    def __init__(self, plane_data, instr,
                 crystal_params=None, sample_rmat=None,
                 min_energy=5., max_energy=35.,
                 ):
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

    def overlay(self, display_mode='raw'):
        sim_data = self.instrument.simulate_laue_pattern(
            self.plane_data,
            minEnergy=self.min_energy,
            maxEnergy=self.max_energy,
            rmat_s=self.sample_rmat,
            grain_params=[self.crystal_params, ])
        point_groups = dict.fromkeys(sim_data)
        for det_key, psim in sim_data.items():
            xy_det, hkls_in, angles, dspacing, energy = psim
            idx = ~np.isnan(energy)
            if display_mode == 'polar':
                point_groups[det_key] = angles[idx, :]
            elif display_mode in ['raw', 'cartesian']:
                # Convert to pixel coordinates
                panel = self.instrument.detectors[det_key]
                point_groups[det_key] = panel.cartToPixel(xy_det[idx, :])
        return point_groups
