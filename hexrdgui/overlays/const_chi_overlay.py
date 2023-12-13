from dataclasses import asdict, dataclass

import numpy as np

from hexrd import constants

from hexrdgui.constants import OverlayType, ViewType
from hexrdgui.overlays.overlay import Overlay
from hexrdgui.utils.const_chi import generate_ring_points_chi
from hexrdgui.utils.conversions import (
    angles_to_stereo, cart_to_angles, cart_to_pixels
)


class ConstChiOverlay(Overlay):

    type = OverlayType.const_chi
    data_key = 'data'
    ranges_key = None

    def __init__(self, material_name, chi_values=None, tvec=None,
                 chi_values_serialized=None, **overlay_kwargs):
        # chi_values_serialized is only used if chi_values is None.
        # It is used for state loading.
        Overlay.__init__(self, material_name, **overlay_kwargs)

        if chi_values is None:
            if chi_values_serialized is not None:
                chi_values = chi_values_serialized
            else:
                chi_values = []

        if tvec is None:
            tvec = constants.zeros_3.copy()

        self.chi_values = chi_values
        self.tvec = tvec

        self.setup_connections()

    def setup_connections(self):
        from hexrdgui.hexrd_config import HexrdConfig
        HexrdConfig().sample_tilt_modified.connect(
            self.on_sample_tilt_modified)

    @property
    def child_attributes_to_save(self):
        # These names must be identical here, as attributes, and as
        # arguments to the __init__ method.
        return [
            'chi_values_serialized',
            'tvec',
        ]

    @property
    def chi_values(self):
        return self._chi_values

    @chi_values.setter
    def chi_values(self, v):
        values = []
        for x in v:
            if isinstance(x, dict):
                x = ChiValue(**x)
            elif not isinstance(x, ChiValue):
                x = ChiValue(x)

            values.append(x)

        # If there are any duplicate values, only keep the first
        raw_values = [x.value for x in values]
        keep_indices = np.unique(raw_values, return_index=True)[1]
        values = [x for i, x in enumerate(values) if i in keep_indices]

        self._chi_values = sorted(values)

    @property
    def chi_values_serialized(self):
        return [asdict(x) for x in self.chi_values]

    @chi_values_serialized.setter
    def chi_values_serialized(self, v):
        # The regular setter can already handle this
        self.chi_values = v

    @property
    def tvec(self):
        return self._tvec

    @tvec.setter
    def tvec(self, v):
        self._tvec = np.asarray(v, float)

    @property
    def sample_tilt(self):
        from hexrdgui.hexrd_config import HexrdConfig
        return HexrdConfig().sample_tilt

    @sample_tilt.setter
    def sample_tilt(self, v):
        from hexrdgui.hexrd_config import HexrdConfig
        HexrdConfig().sample_tilt = v

    def on_sample_tilt_modified(self):
        self.update_needed = True

    def generate_overlay(self):
        instr = self.instrument

        data = {
            det_key: {'data': [], 'chi': []}
            for det_key in instr.detectors
        }
        for chi_value in self.chi_values:
            if not chi_value.visible:
                continue

            chi = chi_value.value
            result = generate_ring_points_chi(chi, self.sample_tilt, instr)

            for det_key, xys in result.items():
                if len(xys) == 0:
                    continue

                # Convert to the display mode
                pts = self.cart_to_display_mode(xys, instr, det_key)

                data[det_key]['chi'].append(chi)
                # Add a nans row so they can be combined easier for drawing
                data[det_key]['data'].append(np.vstack([pts, nans_row]))

        return data

    def cart_to_display_mode(self, xys, instr, det_key):
        panel = instr.detectors[det_key]
        if self.display_mode in (ViewType.raw, ViewType.cartesian):
            # Find the distances between all points, and insert nans between
            # any points that are very far apart (10x the median)
            distances = np.sqrt(np.sum(np.diff(xys, axis=0)**2, axis=1))
            tolerance = np.nanmedian(distances) * 10
            gaps, = np.nonzero(np.abs(distances) > np.abs(tolerance))
            xys = np.insert(xys, gaps + 1, np.nan, axis=0)

            if self.display_mode == ViewType.cartesian:
                # Already correct
                return xys
            else:
                return cart_to_pixels(xys, panel)

        # Must be polar or stereo
        from hexrdgui.hexrd_config import HexrdConfig
        kwargs = {
            'xys': xys,
            'panel': panel,
            'eta_period': HexrdConfig().polar_res_eta_period,
            'tvec_s': instr.tvec,
        }
        angs = cart_to_angles(**kwargs)

        diff = np.diff(angs[:, 1])
        # # Some detectors, such as cylindrical, can easily end up
        # # with points that are connected far apart, and run across
        # # other detectors. Thus, we should insert nans at any gaps.
        # # FIXME: is this a reasonable tolerance?
        delta_eta_est = np.nanmedian(diff)
        tolerance = delta_eta_est * 2
        gaps, = np.nonzero(np.abs(diff) > np.abs(tolerance))
        angs = np.insert(angs, gaps + 1, np.nan, axis=0)

        if self.display_mode == ViewType.polar:
            # We are done!
            return angs

        # We are in stereo
        return angles_to_stereo(
            np.radians(angs),
            instr,
            HexrdConfig().stereo_size,
        )

    @property
    def default_style(self):
        return {
            'data': {
                'c': '#e01b24',  # Red
                'ls': 'dashdot',
                'lw': 1.0,
            }
        }

    @property
    def default_highlight_style(self):
        return {
            'data': {
                'c': '#ff00ff',  # Magenta
                'ls': 'dashdot',
                'lw': 3.0,
            }
        }

    @property
    def refinement_labels(self):
        return []

    @property
    def default_refinements(self):
        return []

    def pad_picks_data(self):
        # Const chi overlays do not currently support picks data
        pass

    @property
    def has_picks_data(self):
        # Const chi overlays do not currently support picks data
        return False

    @property
    def calibration_picks_polar(self):
        # Const chi overlays do not currently support picks data
        return []

    @calibration_picks_polar.setter
    def calibration_picks_polar(self, picks):
        # Const chi overlays do not currently support picks data
        pass

    @property
    def has_widths(self):
        # Const chi overlays do not currently support widths
        return False


@dataclass
class ChiValue:
    value: float
    hkl: str = 'None'
    visible: bool = True

    def __lt__(self, other):
        return self.value < other.value


# Constants
nans_row = np.nan * np.ones((1, 2))
