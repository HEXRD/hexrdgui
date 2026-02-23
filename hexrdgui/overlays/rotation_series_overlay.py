import numpy as np

from hexrd.findorientations import _process_omegas
from hexrd.rotations import mapAngle

from hexrdgui.constants import OverlayType, ViewType
from hexrdgui.overlays.constants import (
    crystal_refinement_labels,
    default_crystal_params,
    default_crystal_refinements,
)
from hexrdgui.overlays.overlay import Overlay
from hexrdgui.utils.conversions import angles_to_stereo


class RotationSeriesOverlay(Overlay):

    type = OverlayType.rotation_series
    data_key = 'data'
    ranges_key = 'ranges'

    def __init__(
        self,
        material_name,
        crystal_params=None,
        eta_ranges=None,
        ome_ranges=None,
        ome_period=None,
        aggregated=True,
        ome_width=np.radians(1.5).item(),
        tth_width=np.radians(0.25).item(),
        eta_width=np.radians(1.0).item(),
        sync_ome_period=True,
        sync_ome_ranges=True,
        **overlay_kwargs
    ):
        super().__init__(material_name, **overlay_kwargs)

        if crystal_params is None:
            crystal_params = default_crystal_params()

        if eta_ranges is None:
            eta_ranges = [[-np.pi, np.pi]]

        if ome_ranges is None:
            ome_ranges = [[-np.pi, np.pi]]

        if ome_period is None:
            ome_period = [-np.pi, np.pi]

        self.crystal_params = crystal_params
        self.eta_ranges = eta_ranges
        self.ome_ranges = ome_ranges
        self.ome_period = ome_period
        self.aggregated = aggregated
        self.ome_width = ome_width
        self.tth_width = tth_width
        self.eta_width = eta_width
        self._sync_ome_period = sync_ome_period
        self._sync_ome_ranges = sync_ome_ranges

        # In case we need to sync up the omegas
        self.sync_omegas()
        self.setup_connections()

    def setup_connections(self):
        super().setup_connections()

        from hexrdgui.image_load_manager import ImageLoadManager

        ImageLoadManager().omegas_updated.connect(self.sync_omegas)

    @property
    def child_attributes_to_save(self):
        # These names must be identical here, as attributes, and as
        # arguments to the __init__ method.
        return [
            'crystal_params',
            'eta_ranges',
            'ome_ranges',
            'ome_period',
            'aggregated',
            'ome_width',
            'tth_width',
            'eta_width',
            'sync_ome_period',
            'sync_ome_ranges',
        ]

    @property
    def has_widths(self):
        widths = ['tth_width', 'eta_width']
        return all(getattr(self, x) is not None for x in widths)

    @property
    def crystal_params(self):
        return self._crystal_params

    @crystal_params.setter
    def crystal_params(self, x):
        assert len(x) == 12, 'input must be array-like with length 12'
        self._crystal_params = np.array(x)

    @property
    def eta_ranges(self):
        return self._eta_ranges

    @eta_ranges.setter
    def eta_ranges(self, x):
        assert hasattr(x, '__len__'), 'eta ranges must be a list of 2-tuples'
        self._eta_ranges = x

    @property
    def ome_ranges(self):
        return self._ome_ranges

    @ome_ranges.setter
    def ome_ranges(self, x):
        assert hasattr(x, '__len__'), 'ome ranges must be a list of 2-tuples'
        self._ome_ranges = x

    @property
    def ome_period(self):
        return self._ome_period

    @ome_period.setter
    def ome_period(self, v):
        self._ome_period = v

    @property
    def aggregated(self):
        from hexrdgui.hexrd_config import HexrdConfig

        # Even though we may have aggregated set to be True, do not
        # aggregate unless the conditions are right.
        force_aggregated = HexrdConfig().is_aggregated or not HexrdConfig().has_omegas
        if force_aggregated:
            return True

        return self._aggregated

    @aggregated.setter
    def aggregated(self, v):
        self._aggregated = v

    @property
    def sync_ome_period(self):
        return self._sync_ome_period

    @sync_ome_period.setter
    def sync_ome_period(self, v):
        if self.sync_ome_period == v:
            return

        self._sync_ome_period = v
        self.sync_omegas()

    @property
    def sync_ome_ranges(self):
        return self._sync_ome_ranges

    @sync_ome_ranges.setter
    def sync_ome_ranges(self, v):
        if self.sync_ome_ranges == v:
            return

        self._sync_ome_ranges = v
        self.sync_omegas()

    @property
    def refinement_labels(self):
        return crystal_refinement_labels()

    @property
    def default_refinements(self):
        return default_crystal_refinements()

    @property
    def has_picks_data(self):
        # Rotation series overlays do not currently support picks data
        return False

    @property
    def calibration_picks_polar(self):
        # Rotation series overlays do not currently support picks data
        return []

    @calibration_picks_polar.setter
    def calibration_picks_polar(self, picks):
        # Rotation series overlays do not currently support picks data
        pass

    def generate_overlay(self):
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
        from hexrdgui.hexrd_config import HexrdConfig

        instr = self.instrument
        display_mode = self.display_mode
        sim_data = instr.simulate_rotation_series(
            self.plane_data,
            [
                self.crystal_params,
            ],
            eta_ranges=self.eta_ranges,
            ome_ranges=self.ome_ranges,
            ome_period=self.ome_period,
        )
        point_groups = {}
        for det_key, psim in sim_data.items():
            panel = instr.detectors[det_key]
            valid_ids, valid_hkls, valid_angs, valid_xys, ang_pixel_size = psim
            omegas = valid_angs[0][:, 2]

            angles, _ = panel.cart_to_angles(valid_xys[0], tvec_c=self.tvec_c)

            # Fix eta period
            angles[:, 1] = mapAngle(
                angles[:, 1], np.radians(self.eta_period), units='radians'
            )

            if display_mode == ViewType.polar:
                data = np.degrees(angles)
            elif display_mode == ViewType.stereo:
                data = angles_to_stereo(
                    angles,
                    instr,
                    HexrdConfig().stereo_size,
                )
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
        if not self.has_widths:
            return []

        widths = (self.tth_width, self.eta_width)
        # Put the first point at the end to complete the square
        tol_box = np.array(
            [[0.5, 0.5], [0.5, -0.5], [-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5]]
        )
        ranges = []
        for spot in spots:
            corners = np.tile(spot, (5, 1)) + tol_box * np.tile(widths, (5, 1))
            ranges.append(corners)

        return ranges

    def range_data(self, spots, display_mode, panel):
        data = self.rectangular_range_data(spots, display_mode, panel)

        # Add a nans row at the end of each range
        # This makes it easier to vstack them for plotting
        data = [np.append(x, nans_row, axis=0) for x in data]

        return data

    def rectangular_range_data(self, spots, display_mode, panel):
        from hexrdgui.hexrd_config import HexrdConfig

        range_corners = self.range_corners(spots)
        if display_mode == ViewType.polar:
            # All done...
            return np.degrees(range_corners)
        elif display_mode == ViewType.stereo:
            # Convert the angles to stereo ij
            return [
                angles_to_stereo(
                    angles,
                    self.instrument,
                    HexrdConfig().stereo_size,
                )
                for angles in range_corners
            ]

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

    @property
    def default_style(self):
        return {
            'data': {'c': '#00ffff', 'marker': 'o', 's': 2.0},  # Cyan
            'ranges': {'c': '#00ff00', 'ls': 'dotted', 'lw': 1.0},  # Green
        }

    @property
    def default_highlight_style(self):
        return {
            'data': {'c': '#ff00ff', 'ls': 'solid', 'lw': 3.0},  # Magenta
            'ranges': {'c': '#ff00ff', 'ls': 'dotted', 'lw': 3.0},  # Magenta
        }

    def on_new_images_loaded(self):
        self.sync_omegas()

    def sync_omegas(self):
        from hexrdgui.hexrd_config import HexrdConfig

        ims_dict = HexrdConfig().omega_imageseries_dict
        if ims_dict is None:
            ome_period = None
            ome_ranges = None
        else:
            ome_period, ome_ranges = _process_omegas(ims_dict)

        if self.sync_ome_period and ome_period is not None:
            self.ome_period = np.radians(ome_period)
            self.update_needed = True

        if self.sync_ome_ranges and ome_ranges is not None:
            self.ome_ranges = np.radians(ome_ranges)
            self.update_needed = True

        if self.update_needed:
            HexrdConfig().overlay_config_changed.emit()
            HexrdConfig().update_overlay_editor.emit()


# Constants
nans_row = np.nan * np.ones((1, 2))
