import copy

import numpy as np

from hexrd import constants
from hexrd.material import unitcell

from hexrd.transforms import xfcapi

from hexrdgui.constants import OverlayType, ViewType
from hexrdgui.overlays.overlay import Overlay
from hexrdgui.polar_distortion_object import PolarDistortionObject
from hexrdgui.utils.conversions import (
    angles_to_cart, angles_to_stereo, cart_to_angles
)


class PowderOverlay(Overlay, PolarDistortionObject):

    type = OverlayType.powder
    data_key = 'rings'
    ranges_key = 'rbnds'
    ranges_indices_key = 'rbnd_indices'

    def __init__(self, material_name, tvec=None, eta_steps=360,
                 tth_distortion_type=None, tth_distortion_kwargs=None,
                 clip_with_panel_buffer=False, **overlay_kwargs):
        Overlay.__init__(self, material_name, **overlay_kwargs)

        if tvec is None:
            tvec = constants.zeros_3.copy()

        if tth_distortion_kwargs is None:
            tth_distortion_kwargs = {}

        self.tvec = tvec
        self.eta_steps = eta_steps
        self.tth_distortion_type = tth_distortion_type
        self.tth_distortion_kwargs = tth_distortion_kwargs
        self.clip_with_panel_buffer = clip_with_panel_buffer

    @property
    def child_attributes_to_save(self):
        # These names must be identical here, as attributes, and as
        # arguments to the __init__ method.
        return [
            'tvec',
            'eta_steps',
            'tth_distortion_type',
            'tth_distortion_kwargs',
            'clip_with_panel_buffer',
        ]

    @property
    def has_widths(self):
        return self.material.planeData.tThWidth is not None

    @property
    def tvec(self):
        if self.has_tth_distortion:
            # If there is a distortion, act as if there is no tvec
            return constants.zeros_3.copy()

        return self._tvec

    @tvec.setter
    def tvec(self, x):
        x = np.asarray(x, float).flatten()
        assert len(x) == 3, "tvec input must have exactly 3 elements"
        self._tvec = x

    @property
    def eta_steps(self):
        return self._eta_steps

    @eta_steps.setter
    def eta_steps(self, x):
        assert isinstance(x, int), 'input must be an int'
        self._eta_steps = x

    @property
    def delta_eta(self):
        return 360 / self.eta_steps

    @property
    def all_refinements(self):
        # This doesn't take into account crystal symmetry
        if not hasattr(self, '_all_refinements'):
            self._all_refinements = self.default_refinements
        return self._all_refinements

    @all_refinements.setter
    def all_refinements(self, v):
        if len(v) != 6:
            raise Exception(f'{len(v)=} must be 6')
        self._all_refinements = np.asarray(v)

    @property
    def refinements(self):
        # Only return the required indices
        return self.all_refinements[self.refinement_indices]

    @refinements.setter
    def refinements(self, v):
        if len(v) == 6:
            self.all_refinements = v
        elif len(v) == len(self.refinement_indices):
            self.all_refinements[self.refinement_indices] = v
        else:
            msg = f'{v=} must be length 6 or {len(self.refinement_indices)=}'
            raise Exception(msg)

    @property
    def refinement_indices(self):
        if self.material is None:
            return np.asarray(range(6))
        ltype = self.material.unitcell.latticeType
        return np.asarray(unitcell._rqpDict[ltype][0])

    @property
    def all_refinement_labels(self):
        return np.asarray(['a', 'b', 'c', 'α', 'β', 'γ'])

    @property
    def refinement_labels(self):
        if self.material is None:
            return self.all_refinement_labels

        return self.all_refinement_labels[self.refinement_indices]

    @property
    def default_refinements(self):
        return np.asarray([False] * 6)

    def pad_picks_data(self):
        for k, v in self.data.items():
            num_hkls = len(self.data[k]['hkls'])
            current = self.calibration_picks.setdefault(k, [])
            while len(current) < num_hkls:
                current.append([])

    @property
    def has_picks_data(self):
        for det_key, hkl_list in self.calibration_picks.items():
            for hkl_picks in hkl_list:
                if hkl_picks:
                    return True

        return False

    @property
    def calibration_picks_polar(self):
        # Convert from cartesian to polar
        instr = self.instrument
        picks = copy.deepcopy(self.calibration_picks)
        for det_key, det_picks in picks.items():
            panel = instr.detectors[det_key]
            for i in range(len(det_picks)):
                if len(det_picks[i]) == 0:
                    continue

                det_picks[i] = cart_to_angles(
                    det_picks[i],
                    panel,
                    self.eta_period,
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
            for i in range(len(det_picks)):
                if len(det_picks[i]) == 0:
                    continue

                det_picks[i] = angles_to_cart(det_picks[i], panel).tolist()

        self.calibration_picks = picks

    def generate_overlay(self):
        instr = self.instrument
        plane_data = self.plane_data
        display_mode = self.display_mode

        tths = plane_data.getTTh()
        hkls = plane_data.getHKLs()
        etas = np.radians(
            np.linspace(
                -180., 180., num=self.eta_steps + 1
            )
        )

        if tths.size == 0:
            # No overlays
            return {}

        if plane_data.tThWidth is not None:
            # Need to get width data as well
            indices, ranges = plane_data.getMergedRanges()
            r_lower = [r[0] for r in ranges]
            r_upper = [r[1] for r in ranges]

        point_groups = {}
        for det_key, panel in instr.detectors.items():
            keys = ['rings', 'rbnds', 'rbnd_indices', 'hkls']
            point_groups[det_key] = {key: [] for key in keys}
            ring_pts, skipped_tth = self.generate_ring_points(
                instr, tths, etas, panel, display_mode)

            det_hkls = [x for i, x in enumerate(hkls) if i not in skipped_tth]

            point_groups[det_key]['rings'] = ring_pts
            point_groups[det_key]['hkls'] = det_hkls

            if plane_data.tThWidth is not None:
                # Generate the ranges too
                lower_pts, lower_skipped = self.generate_ring_points(
                    instr, r_lower, etas, panel, display_mode
                )
                upper_pts, upper_skipped = self.generate_ring_points(
                    instr, r_upper, etas, panel, display_mode
                )
                lower_indices = [x for i, x in enumerate(indices)
                                 if i not in lower_skipped]
                upper_indices = [x for i, x in enumerate(indices)
                                 if i not in upper_skipped]

                point_groups[det_key]['rbnds'] += lower_pts
                point_groups[det_key]['rbnd_indices'] += lower_indices

                point_groups[det_key]['rbnds'] += upper_pts
                point_groups[det_key]['rbnd_indices'] += upper_indices

        return point_groups

    def generate_ring_points(self, instr, tths, etas, panel, display_mode):
        from hexrdgui.hexrd_config import HexrdConfig

        ring_pts = []
        skipped_tth = []

        # Grab the distortion object if we have one
        sd = None
        if self.has_tth_distortion:
            sd = self.tth_distortion_dict[panel.name]

        # Apply tth_distortion if:
        # 1. tth_distortion was set (sd is not None)
        # 2. We are not distorting the polar image with the current overlay
        distortion_object = HexrdConfig().polar_tth_distortion_object
        polar_distortion_with_self = (
            display_mode in (ViewType.polar, ViewType.stereo) and
            distortion_object is self
        )
        apply_distortion = (
            sd is not None and
            not polar_distortion_with_self
        )

        if apply_distortion:
            # Offset the distortion if we are distorting the polar image
            # with a different overlay, and we have all the required
            # variables defined.
            polar_corr_field = HexrdConfig().polar_corr_field_polar
            polar_angular_grid = HexrdConfig().polar_angular_grid

            offset_distortion = (
                display_mode in (ViewType.polar, ViewType.stereo) and
                distortion_object is not None and
                polar_corr_field is not None and
                polar_angular_grid is not None
            )

            if offset_distortion:
                # Set these up outside of the loop
                polar_field = polar_corr_field.filled(np.nan)
                eta_centers, tth_centers = polar_angular_grid
                first_eta_col = eta_centers[:, 0]
                first_tth_row = tth_centers[0]

        for i, tth in enumerate(tths):
            # construct ideal angular coords
            ang_crds_full = np.vstack([np.tile(tth, len(etas)), etas]).T

            # Convert nominal powder angle coords to cartesian
            # !!! Tricky business; here we must consider _both_ the SAMPLE
            #     CS origin and anything specified for the XRD COM for the
            #     overlay.  This is so they get properly mapped back to the
            #     the proper cartesian coords.
            xys_full = panel.angles_to_cart(
                ang_crds_full,
                tvec_s=instr.tvec,
                tvec_c=self.tvec
            )

            # skip if ring not on panel
            if len(xys_full) == 0:
                skipped_tth.append(i)
                continue

            # clip to detector panel
            xys, on_panel = panel.clip_to_panel(
                xys_full, buffer_edges=self.clip_with_panel_buffer
            )

            if apply_distortion:
                # Apply distortion correction
                ang_crds = sd.apply(xys)

                if offset_distortion:
                    # Need to offset according to another overlay's distortion

                    # Need to ensure the angles are mapped
                    ang_crds[:, 1] = xfcapi.mapAngle(
                        ang_crds[:, 1], np.radians(self.eta_period),
                        units='radians'
                    )

                    # Compute and apply offset
                    for ic, ang_crd in enumerate(ang_crds):
                        i = np.argmin(np.abs(ang_crd[0] - first_tth_row))
                        j = np.argmin(np.abs(ang_crd[1] - first_eta_col))
                        ang_crds[ic, 0] += polar_field[j, i]

                if display_mode in (ViewType.raw, ViewType.cartesian):
                    # These need the updated xys
                    xys = panel.angles_to_cart(ang_crds)

            if display_mode in [ViewType.polar, ViewType.stereo]:
                if not apply_distortion:
                    # The ang_crds have not yet been computed. Do so now.
                    # In the polar view, the nominal angles refer to the SAMPLE
                    # CS origin, so we omit the addition of any offset to the
                    # diffraction COM in the sample frame!
                    ang_crds, _ = panel.cart_to_angles(
                        xys,
                        tvec_s=instr.tvec
                    )

                if len(ang_crds) == 0:
                    skipped_tth.append(i)
                    continue

                # Convert to degrees
                ang_crds = np.degrees(ang_crds)

                # fix eta period
                ang_crds[:, 1] = xfcapi.mapAngle(
                    ang_crds[:, 1], self.eta_period, units='degrees'
                )

                # sort points for monotonic eta
                eidx = np.argsort(ang_crds[:, 1])
                ang_crds = ang_crds[eidx, :]

                diff = np.diff(ang_crds[:, 1])
                if len(diff) == 0:
                    skipped_tth.append(i)
                    continue

                # Some detectors, such as cylindrical, can easily end up
                # with points that are connected far apart, and run across
                # other detectors. Thus, we should insert nans at any gaps.
                # FIXME: is this a reasonable tolerance?
                delta_eta_est = np.nanmedian(diff)
                tolerance = delta_eta_est * 2
                gaps, = np.nonzero(diff > tolerance)
                ang_crds = np.insert(ang_crds, gaps + 1, np.nan, axis=0)

                if display_mode == ViewType.polar:
                    # append to list with nan padding
                    ring_pts.append(np.vstack([ang_crds, nans_row]))
                elif display_mode == ViewType.stereo:
                    # Convert back to radians
                    ang_crds = np.radians(ang_crds)

                    # Convert the ang_crds to stereo ij
                    stereo_ij = angles_to_stereo(
                        ang_crds,
                        instr,
                        HexrdConfig().stereo_size,
                    )

                    # append to list with nan padding
                    ring_pts.append(np.vstack([stereo_ij, nans_row]))

            elif display_mode in [ViewType.raw, ViewType.cartesian]:

                if display_mode == ViewType.raw:
                    # !!! distortion
                    if panel.distortion is not None:
                        xys = panel.distortion.apply_inverse(xys)

                    # Convert to pixel coordinates and swap columns
                    xys = panel.cartToPixel(xys)[:, [1, 0]]

                diff_tol = np.radians(self.delta_eta) + 1e-4
                ring_breaks = np.where(
                    np.abs(np.diff(etas[on_panel])) > diff_tol
                )[0] + 1
                n_segments = len(ring_breaks) + 1

                if n_segments == 1:
                    ring_pts.append(np.vstack([xys, nans_row]))
                else:
                    src_len = sum(on_panel)
                    dst_len = src_len + len(ring_breaks)
                    nxys = np.nan*np.ones((dst_len, 2))
                    ii = 0
                    for i in range(n_segments - 1):
                        jj = ring_breaks[i]
                        nxys[ii + i:jj + i, :] = xys[ii:jj, :]
                        ii = jj
                    i = n_segments - 1
                    nxys[ii + i:, :] = xys[ii:, :]
                    ring_pts.append(np.vstack([nxys, nans_row]))

        return ring_pts, skipped_tth

    # START PolarDistortionObject mixin reroutes
    @property
    def has_tth_distortion(self):
        return self.has_pinhole_distortion

    @property
    def tth_distortion_dict(self):
        return self.pinhole_distortion_dict(self.instrument)

    @property
    def has_polar_tth_displacement_field(self):
        return self.has_polar_pinhole_displacement_field

    @property
    def tth_displacement_field(self):
        return self.pinhole_displacement_field(self.instrument)

    def create_polar_tth_displacement_field(self):
        return self.create_polar_pinhole_displacement_field(self.instrument)

    @property
    def pinhole_distortion_type(self):
        return self.tth_distortion_type

    @property
    def pinhole_distortion_kwargs(self):
        kwargs = self.tth_distortion_kwargs.copy()
        if self.pinhole_distortion_type == 'RyggPinholeDistortion':
            # Add our absorption length
            kwargs['absorption_length'] = self.material.absorption_length
        return kwargs
    # END PolarDistortionObject mixin reroutes

    @property
    def default_style(self):
        return {
            'data': {
                'c': '#00ffff',  # Cyan
                'ls': 'solid',
                'lw': 1.0
            },
            'ranges': {
                'c': '#00ff00',  # Green
                'ls': 'dotted',
                'lw': 1.0
            }
        }

    @property
    def default_highlight_style(self):
        return {
            'data': {
                'c': '#ff00ff',  # Magenta
                'ls': 'solid',
                'lw': 3.0
            },
            'ranges': {
                'c': '#ff00ff',  # Magenta
                'ls': 'dotted',
                'lw': 3.0
            }
        }


# Constants
nans_row = np.nan * np.ones((1, 2))
