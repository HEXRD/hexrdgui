import numpy as np

from hexrd import constants

from hexrd.ui.constants import ViewType


class MonoRotationSeriesSpotOverlay:
    def __init__(self, plane_data, instr,
                 crystal_params=None,
                 eta_ranges=None,
                 ome_ranges=None,
                 ome_period=None,
                 aggregation_mode=None
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
            assert len(crystal_params) == 12, \
                "crystal parameters must have length 12"
            self._crystal_params = crystal_params

        if eta_ranges is None:
            self._eta_ranges = [(-np.pi, np.pi), ]
        else:
            assert hasattr(eta_ranges, '__len__'), \
                'eta ranges must be a list of 2-tuples'
            # !!! need better check
            self._eta_ranges = eta_ranges

        if ome_ranges is None:
            self._ome_ranges = [(-np.pi, np.pi), ]
        else:
            assert hasattr(ome_ranges, '__len__'), \
                'ome ranges must be a list of 2-tuples'
            # !!! need better check
            self._ome_ranges = ome_ranges

        if ome_period is None:
            self._ome_period = self._ome_ranges[0][0] + np.r_[0., 2*np.pi]
        else:
            self._ome_period = ome_period

        self._aggregation_mode = aggregation_mode

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

    @property
    def eta_ranges(self):
        return self._eta_ranges

    @eta_ranges.setter
    def eta_ranges(self, x):
        # FIXME: need a check here
        self._eta_ranges = x

    @property
    def ome_ranges(self):
        return self._ome_ranges

    @ome_ranges.setter
    def ome_ranges(self, x):
        # FIXME: need a check here
        self._ome_ranges = x

    @property
    def ome_period(self):
        return self._ome_period

    @property
    def aggregation_mode(self):
        return self._aggregation_mode

    @aggregation_mode.setter
    def aggregation_mode(self, x):
        assert x in ['Maximum', 'Median', 'Average', 'None']
        if x == 'None':
            self._aggregation_mode = None
        else:
            self._aggregation_mode = x

    def overlay(self, display_mode=ViewType.raw):
        """
        Returns appropriate point groups for displaying bragg reflection
        locations for a monochromatic rotation series.

        Parameters
        ----------
        display_mode : TYPE, optional
            DESCRIPTION. The default is ViewType.raw.

        Raises
        ------
        NotImplementedError
            Don't have the 3-d case for plotting on un-aggregated imageseries
            yet.
            TODO: bin omega output as frames; functions exist in
            imageseries.omega

        Returns
        -------
        point_groups : TYPE
            DESCRIPTION.

        """
        sim_data = self.instrument.simulate_rotation_series(
            self.plane_data, [self.crystal_params, ],
            eta_ranges=self.eta_ranges,
            ome_ranges=self.ome_ranges,
            ome_period=self.ome_period
        )
        point_groups = dict.fromkeys(sim_data)
        for det_key, psim in sim_data.items():
            valid_ids, valid_hkls, valid_angs, valid_xys, ang_pixel_size = psim
            if display_mode == ViewType.polar:
                if self.aggregation_mode is None:
                    raise NotImplementedError
                else:
                    point_groups[det_key] = valid_angs[0]
            elif display_mode in [ViewType.raw, ViewType.cartesian]:
                if self.aggregation_mode is None:
                    raise NotImplementedError
                else:
                    point_groups[det_key] = valid_xys[0]
        return point_groups
