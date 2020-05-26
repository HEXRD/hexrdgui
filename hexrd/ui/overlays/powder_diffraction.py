import numpy as np


nans_row = np.nan*np.ones((1, 2))


class PowderLineOverlay(object):
    def __init__(self, plane_data, instr, eta_steps=360):
        self._plane_data = plane_data
        self._instrument = instr
        self._eta_steps = eta_steps

    @property
    def plane_data(self):
        return self._plane_data

    @property
    def instrument(self):
        return self._instrument

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

    def overlay(self, display_mode='raw'):
        """
        """
        tths = self.plane_data.getTTh()

        etas = np.radians(
            self.delta_eta*np.linspace(
                0., self.eta_steps, num=self.eta_steps + 1
            )
        )
        point_groups = dict.fromkeys(self.instrument.detectors)
        for det_key, panel in self.instrument.detectors.items():
            ring_pts = []
            for tth in tths:
                ang_crds = np.vstack([np.tile(tth, len(etas)), etas]).T
                if display_mode == 'polar':
                    ring_pts.append(np.vstack([ang_crds, nans_row]))
                elif display_mode in ['raw', 'cartesian']:
                    xys_full = panel.angles_to_cart(ang_crds)
                    xys, on_panel = panel.clip_to_panel(
                        xys_full, buffer_edges=False
                    )
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
            point_groups[det_key] = np.vstack(ring_pts)
        return point_groups
