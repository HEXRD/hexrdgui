import numpy as np

from hexrd import constants

from hexrd.ui.constants import ViewType


class RotationSeriesSpotOverlay:
    def __init__(self, plane_data, instr,
                 crystal_params=None,
                 eta_ranges=None,
                 ome_ranges=None,
                 ome_period=None,
                 eta_period=np.r_[-180., 180.],
                 aggregated=True,
                 ome_width=np.radians(5.0),
                 tth_width=None,
                 eta_width=None):

        # FIXME: eta_period is currently not in use

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

        self.aggregated = aggregated
        self.ome_width = ome_width
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

    @property
    def widths_enabled(self):
        widths = ['tth_width', 'eta_width']
        return all(getattr(self, x) is not None for x in widths)

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
        point_groups = {}
        for det_key, psim in sim_data.items():
            panel = self.instrument.detectors[det_key]
            valid_ids, valid_hkls, valid_angs, valid_xys, ang_pixel_size = psim
            angles = valid_angs[0][:, :2]
            omegas = valid_angs[0][:, 2]

            if display_mode == ViewType.polar:
                data = np.degrees(angles)
            elif display_mode in [ViewType.raw, ViewType.cartesian]:
                data = valid_xys[0]
                if display_mode == ViewType.raw:
                    # If raw, convert to pixels
                    data[:] = panel.cartToPixel(data)
                    data[:, [0, 1]] = data[:, [1, 0]]

            ranges = self.range_data(angles, display_mode, panel)
            point_groups[det_key] = {
                'data': data,
                'aggregated': self.aggregated,
                'omegas': np.degrees(omegas),
                'omega_width': np.degrees(self.ome_width),
                'ranges': ranges,
            }

        return point_groups

    @property
    def tvec_c(self):
        if self.crystal_params is None:
            return None
        return self.crystal_params[3:6].reshape(3, 1)

    def range_corners(self, spots):
        # spots should be in degrees
        if not self.widths_enabled:
            return []

        widths = (self.tth_width, self.eta_width)
        # Put the first point at the end to complete the square
        tol_box = np.array(
            [[0.5, 0.5],
             [0.5, -0.5],
             [-0.5, -0.5],
             [-0.5, 0.5],
             [0.5, 0.5]]
        )
        ranges = []
        for spot in spots:
            corners = np.tile(spot, (5, 1)) + tol_box*np.tile(widths, (5, 1))
            ranges.append(corners)

        return ranges

    def range_data(self, spots, display_mode, panel):
        return self.rectangular_range_data(spots, display_mode, panel)

    def rectangular_range_data(self, spots, display_mode, panel):
        range_corners = self.range_corners(spots)
        if display_mode == ViewType.polar:
            # All done...
            return np.degrees(range_corners)

        # The range data is curved for raw and cartesian.
        # Get more intermediate points so the data reflects this.
        results = []
        for corners in range_corners:
            data = []
            for i in range(len(corners) - 1):
                tmp = np.linspace(corners[i], corners[i + 1])
                data.extend(panel.angles_to_cart(tmp, tvec_c=self.tvec_c))

            data = np.array(data)
            if display_mode == ViewType.raw:
                data = panel.cartToPixel(data)
                data[:, [0, 1]] = data[:, [1, 0]]

            results.append(data)

        return results
