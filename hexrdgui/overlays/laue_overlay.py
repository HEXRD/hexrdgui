import copy
from enum import Enum

import numpy as np

from hexrd import constants
from hexrd.transforms import xfcapi
from hexrd.utils.decorators import numba_njit_if_available

from hexrdgui.constants import OverlayType, ViewType
from hexrdgui.overlays.constants import (
    crystal_refinement_labels, default_crystal_params,
    default_crystal_refinements
)
from hexrdgui.overlays.overlay import Overlay
from hexrdgui.utils.conversions import (
    angles_to_cart, angles_to_stereo, cart_to_angles
)
from hexrdgui.utils.tth_distortion import apply_tth_distortion_if_needed


class LaueOverlay(Overlay):

    type = OverlayType.laue
    hkl_data_key = 'spots'

    def __init__(self, material_name, crystal_params=None, sample_rmat=None,
                 min_energy=5, max_energy=35, tth_width=None, eta_width=None,
                 width_shape=None, label_type=None, label_offsets=None,
                 **overlay_kwargs):
        super().__init__(material_name, **overlay_kwargs)

        if crystal_params is None:
            crystal_params = default_crystal_params()

        if sample_rmat is None:
            sample_rmat = constants.identity_3x3.copy()

        if width_shape is None:
            width_shape = LaueRangeShape.ellipse

        if label_offsets is None:
            label_offsets = [1, 1]

        self.crystal_params = crystal_params
        self.sample_rmat = sample_rmat
        self._min_energy = min_energy
        self._max_energy = max_energy
        self.tth_width = tth_width
        self.eta_width = eta_width
        self.width_shape = width_shape
        self.label_type = label_type
        self.label_offsets = label_offsets

    @property
    def child_attributes_to_save(self):
        # These names must be identical here, as attributes, and as
        # arguments to the __init__ method.
        return [
            'crystal_params',
            'sample_rmat',
            'min_energy',
            'max_energy',
            'tth_width',
            'eta_width',
            'width_shape',
            'label_type',
            'label_offsets',
        ]

    @property
    def has_widths(self):
        widths = ['tth_width', 'eta_width']
        return all(getattr(self, x) is not None for x in widths)

    @property
    def plane_data_no_exclusions(self):
        plane_data = copy.deepcopy(self.plane_data)
        # For Laue overlays, we will use all hkl values
        plane_data.exclusions = None
        return plane_data

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

    @property
    def refinement_labels(self):
        return crystal_refinement_labels()

    @property
    def default_refinements(self):
        return default_crystal_refinements()

    def pad_picks_data(self):
        for k, v in self.data.items():
            num_hkls = len(self.data[k]['hkls'])
            current = self.calibration_picks.setdefault(k, [])
            while len(current) < num_hkls:
                current.append((np.nan, np.nan))

    @property
    def has_picks_data(self):
        for det_key, hkl_list in self.calibration_picks.items():
            if hkl_list and not np.min(np.isnan(hkl_list)):
                return True

        return False

    @property
    def calibration_picks_polar(self):
        # Convert from cartesian to polar
        from hexrdgui.hexrd_config import HexrdConfig

        eta_period = HexrdConfig().polar_res_eta_period

        instr = self.instrument
        picks = copy.deepcopy(self.calibration_picks)
        for det_key, det_picks in picks.items():
            panel = instr.detectors[det_key]
            picks[det_key] = cart_to_angles(
                det_picks,
                panel,
                eta_period,
            ).tolist()

        return picks

    @calibration_picks_polar.setter
    def calibration_picks_polar(self, picks):
        self._validate_picks(picks)

        # Convert from polar to cartesian
        instr = self.instrument
        picks = copy.deepcopy(picks)
        for det_key, det_picks in picks.items():
            panel = instr.detectors[det_key]
            picks[det_key] = angles_to_cart(det_picks, panel).tolist()

        self.calibration_picks = picks

    def generate_overlay(self):
        from hexrdgui.hexrd_config import HexrdConfig

        instr = self.instrument
        display_mode = self.display_mode

        point_groups = {}
        keys = ['spots', 'ranges', 'hkls', 'labels', 'label_offsets']
        for det_key in instr.detectors:
            point_groups[det_key] = {key: [] for key in keys}

        # This will be an empty list if there are none.
        # And if there are none, the Laue simulator produces an error.
        # Guard against that error.
        sym_hkls = self.plane_data.getSymHKLs()
        if not sym_hkls:
            return point_groups

        sim_data = instr.simulate_laue_pattern(
            self.plane_data_no_exclusions,
            minEnergy=self.min_energy,
            maxEnergy=self.max_energy,
            rmat_s=self.sample_rmat,
            grain_params=[self.crystal_params, ])

        for det_key, psim in sim_data.items():
            # grab panel and split out simulation results
            # !!! note that the sim results are lists over number of grains
            #     and here we explicitly have one.
            panel = instr.detectors[det_key]
            xy_det, hkls_in, angles, dspacing, energy = psim

            # find valid points
            idx = ~np.isnan(energy[0])  # there is only one grain here

            # filter results
            xy_data = xy_det[0][idx, :]

            hkls = hkls_in[0][:, idx].T.astype(np.int32)
            point_groups[det_key]['hkls'] = hkls

            angles = angles[0][idx, :]  # these are in radians
            angles[:, 1] = xfcapi.mapAngle(
                angles[:, 1], np.radians(self.eta_period), units='radians'
            )

            energies = energy[0][idx]

            """
            # !!! apply offset corrections to angles
            # convert to angles in LAB ref
            angles_corr, _ = xfcapi.detectorXYToGvec(
                xy_data, panel.rmat, self.sample_rmat,
                panel.tvec, instr.tvec, constants.zeros_3,
                beamVec=instr.beam_vector,
                etaVec=instr.eta_vector
            )
            # FIXME modify output to be array
            angles_corr = np.vstack(angles_corr).T
            angles_corr[:, 1] = xfcapi.mapAngle(
                angles_corr[:, 1], np.radians(self.eta_period), units='radians'
            )
            """
            if display_mode in (ViewType.polar, ViewType.stereo):
                # If the polar view is being distorted, apply this tth
                # distortion to the angles as well.
                angles = apply_tth_distortion_if_needed(angles)

            if display_mode == ViewType.polar:
                # Save the Laue spots as a list instead of a numpy array,
                # so that we can predictably get the id() of spots inside.
                # Numpy arrays do fancy optimizations that break this.
                spots = np.degrees(angles).tolist()
                spots_for_ranges = angles
            elif display_mode == ViewType.stereo:
                # Convert the angles to stereo ij
                spots = angles_to_stereo(
                    angles,
                    instr,
                    HexrdConfig().stereo_size,
                ).tolist()
                spots_for_ranges = angles
            elif display_mode in [ViewType.raw, ViewType.cartesian]:
                if display_mode == ViewType.raw:
                    # Convert to pixel coordinates
                    xy_data = panel.cartToPixel(xy_data)
                    # Swap x and y, they are flipped
                    xy_data[:, [0, 1]] = xy_data[:, [1, 0]]

                spots = xy_data
                spots_for_ranges = angles

            panel = instr.detectors[det_key]
            point_groups[det_key]['spots'] = spots
            point_groups[det_key]['ranges'] = self.range_data(
                spots_for_ranges, display_mode, panel
            )

            # Add labels
            if self.label_type == LaueLabelType.hkls:
                hkls = point_groups[det_key]['hkls']
                labels = [str(tuple(x)) for x in hkls]
            elif self.label_type == LaueLabelType.energy:
                labels = [f'{x:.3g}' for x in energies]
            else:
                labels = []

            point_groups[det_key].update({
                'labels': labels,
                'label_offsets': self.label_offsets,
            })

        return point_groups

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

    @property
    def tvec_c(self):
        if self.crystal_params is None:
            return None
        return self.crystal_params[3:6].reshape(3, 1)

    def range_data(self, spots, display_mode, panel):
        if not self.widths_enabled:
            return []

        range_func = {
            LaueRangeShape.rectangle: self.rectangular_range_data,
            LaueRangeShape.ellipse: self.ellipsoidal_range_data,
        }

        if self.width_shape not in range_func:
            raise Exception(f'Unknown range shape: {self.width_shape}')

        data = range_func[self.width_shape](spots, display_mode, panel)

        # Add a nans row at the end of each range
        # This makes it easier to vstack them for plotting
        data = [np.append(x, nans_row, axis=0) for x in data]

        return data

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

    def ellipsoidal_range_data(self, spots, display_mode, panel):
        from hexrdgui.hexrd_config import HexrdConfig

        num_points = 300
        a = self.tth_width / 2
        b = self.eta_width / 2
        results = []
        for h, k in spots:
            ellipse = ellipse_points(h, k, a, b, num_points)
            results.append(ellipse)

        if display_mode == ViewType.polar:
            return np.degrees(results)

        if display_mode == ViewType.stereo:
            # Convert the angles to stereo ij
            return [angles_to_stereo(
                angles,
                self.instrument,
                HexrdConfig().stereo_size,
            ) for angles in results]

        # Must be cartesian or raw
        if display_mode not in (ViewType.raw, ViewType.cartesian):
            raise Exception(f'Unknown view type: {display_mode}')

        for result in results:
            # Convert to Cartesian
            result[:] = panel.angles_to_cart(result, tvec_c=self.tvec_c)

            if display_mode == ViewType.raw:
                # If raw, convert to pixels
                result[:] = panel.cartToPixel(result)
                result[:, [0, 1]] = result[:, [1, 0]]

        return results

    @property
    def default_style(self):
        return {
            'data': {
                'c': '#00ffff',  # Cyan
                'marker': 'o',
                's': 2.0
            },
            'ranges': {
                'c': '#00ff00',  # Green
                'ls': 'dotted',
                'lw': 1.0
            },
            'labels': {
                'c': '#000000',  # Black
                'size': 10,
                'weight': 'bold',
            }
        }

    @property
    def default_highlight_style(self):
        return {
            'data': {
                'c': '#ff00ff',  # Magenta
                'marker': 'o',
                's': 4.0
            },
            'ranges': {
                'c': '#ff00ff',  # Magenta
                'ls': 'dotted',
                'lw': 3.0
            },
            'labels': {
                'c': '#ff00ff',  # Magenta
                'size': 10,
                'weight': 'bold',
            }
        }


@numba_njit_if_available(cache=True, nogil=True)
def ellipse_points(h, k, a, b, num_points=30):
    # skimage.draw.ellipse_perimeter could work instead, but it is
    # intended to work with indices, and it doesn't sort points.
    # We'll just do our own here using float values and sorting...
    # (x - h)**2 / a**2 + (y - k)**2 / b**2 == 1
    x = np.linspace(h + a, h - a, num_points // 2 + 1)[1:-1]
    y_upper = b * np.sqrt(1 - (x - h)**2 / a**2) + k
    upper = np.vstack((x, y_upper)).T
    lower = np.vstack((x[::-1], 2 * k - y_upper)).T
    right = np.array(((h + a, k),))
    left = np.array(((h - a, k),))
    return np.vstack((right, upper, left, lower, right))


class LaueRangeShape(str, Enum):
    ellipse = 'ellipse'
    rectangle = 'rectangle'


class LaueLabelType(str, Enum):
    hkls = 'hkls'
    energy = 'energy'

# Constants
nans_row = np.nan * np.ones((1, 2))
