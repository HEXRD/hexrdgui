import numpy as np

from hexrd.constants import identity_3x3
from hexrd.transforms import xfcapi
from hexrd.xrdutil import _convert_angles

from hexrd.ui.constants import ViewType


nans_row = np.nan*np.ones((1, 2))


class PowderLineOverlay:
    def __init__(self, plane_data, instr, tvec=np.zeros(3),
                 eta_steps=360, eta_period=np.r_[-180., 180.]):
        self._plane_data = plane_data
        self._instrument = instr
        tvec = np.asarray(tvec, float).flatten()
        assert len(tvec) == 3, "tvec input must have exactly 3 elements"
        self._tvec = tvec
        self._eta_steps = eta_steps

        eta_period = np.asarray(eta_period, float).flatten()
        assert len(eta_period) == 2, "eta period must be a 2-element sequence"
        if xfcapi.angularDifference(eta_period[0], eta_period[1],
                                    units='degrees') > 1e-4:
            raise RuntimeError("period specification is not 360 degrees")
        self._eta_period = eta_period

    @property
    def plane_data(self):
        return self._plane_data

    @property
    def instrument(self):
        return self._instrument

    @property
    def tvec(self):
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
        return 360./float(self.eta_steps)

    @property
    def eta_period(self):
        return self._eta_period

    @eta_period.setter
    def eta_period(self, x):
        x = np.asarray(x, float).flatten()
        assert len(x) == 2, "eta period must be a 2-element sequence"
        if xfcapi.angularDifference(x[0], x[1], units='degrees') > 1e-4:
            raise RuntimeError("period specification is not 360 degrees")
        self._eta_period = x

    def overlay(self, display_mode=ViewType.raw):
        tths = self.plane_data.getTTh()
        etas = np.radians(
            np.linspace(
                -180., 180., num=self.eta_steps + 1
            )
        )

        if self.plane_data.tThWidth is not None:
            # Need to get width data as well
            indices, ranges = self.plane_data.getMergedRanges()
            r_lower = [r[0] for r in ranges]
            r_upper = [r[1] for r in ranges]

        point_groups = {}
        for det_key, panel in self.instrument.detectors.items():
            keys = ['rings', 'rbnds', 'rbnd_indices']
            point_groups[det_key] = {key: [] for key in keys}
            ring_pts = self.generate_ring_points(tths, etas, panel,
                                                 display_mode)
            point_groups[det_key]['rings'] = ring_pts

            if self.plane_data.tThWidth is not None:
                # Generate the ranges too
                lower_pts = self.generate_ring_points(
                    r_lower, etas, panel, display_mode
                )
                upper_pts = self.generate_ring_points(
                    r_upper, etas, panel, display_mode
                )
                for lpts, upts in zip(lower_pts, upper_pts):
                    point_groups[det_key]['rbnds'] += [lpts, upts]
                for ind in indices:
                    point_groups[det_key]['rbnd_indices'] += [ind, ind]

            # Currently, the polar mode draws lines over the whole image.
            # Thus, we only need data from one detector.
            # This can be changed in the future if needed.
            if display_mode == ViewType.polar:
                break

        return point_groups

    def generate_ring_points(self, tths, etas, panel, display_mode):
        ring_pts = []
        for tth in tths:
            ang_crds = np.vstack([np.tile(tth, len(etas)), etas]).T
            if display_mode == ViewType.polar:
                # !!! apply offset correction
                ang_crds = _convert_angles(
                    ang_crds, panel,
                    identity_3x3, self.tvec,
                    beam_vector=self.instrument.beam_vector,
                    eta_vector=self.instrument.eta_vector
                )
                # Swap columns, convert to degrees
                ang_crds[:, [0, 1]] = np.degrees(ang_crds[:, [1, 0]])

                # fix eta period
                ang_crds[:, 0] = xfcapi.mapAngle(
                    ang_crds[:, 0], self.eta_period, units='degrees'
                )

                # sort points for monotonic eta
                eidx = np.argsort(ang_crds[:, 0])
                ang_crds = ang_crds[eidx, :]

                # append to list with nan padding
                ring_pts.append(np.vstack([ang_crds, nans_row]))
            elif display_mode in [ViewType.raw, ViewType.cartesian]:
                # !!! must apply offset
                xys_full = panel.angles_to_cart(ang_crds, tvec_c=self.tvec)

                # !!! distortion
                if panel.distortion is not None:
                    xys_full = panel.distortion.apply_inverse(xys_full)

                # clip to detector panel
                xys, on_panel = panel.clip_to_panel(
                    xys_full, buffer_edges=False
                )

                if display_mode == ViewType.raw:
                    # Convert to pixel coordinates
                    # ??? keep in pixels?
                    xys = panel.cartToPixel(xys)

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

        return ring_pts
