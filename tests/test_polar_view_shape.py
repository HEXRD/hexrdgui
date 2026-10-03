"""Regression test for the polar view shape racing with config changes.

The polar view is warped in a background thread. If the polar config changed
mid-warp, `shape` (read live from the config) no longer matched the angular
grid, and the warp failed with e.g. "cannot reshape array of size 86400 into
shape (360,220)".
"""

import numpy as np

from hexrdgui.calibration.polarview import PolarView
from hexrdgui.hexrd_config import HexrdConfig


def test_shape_follows_angular_grid_not_config(qtbot) -> None:
    # `qtbot` provides the QApplication that HexrdConfig needs
    polar_config = HexrdConfig().config['image']['polar']
    old_tth_max = polar_config['tth_max']

    # A dummy polar view (no instrument) still builds the angular grid
    pv = PolarView(instrument=None)
    grid_shape = pv.angular_grid[0].shape
    assert pv.shape == grid_shape == pv.config_shape
    assert (pv.neta, pv.ntth) == grid_shape

    try:
        # Change the config the way the main thread would while a warp runs.
        # Set it directly to avoid emitting `rerender_needed`.
        polar_config['tth_max'] = old_tth_max - 2 * pv.tth_pixel_size

        assert pv.config_shape != grid_shape
        assert pv.shape == grid_shape
        assert (pv.neta, pv.ntth) == grid_shape
        np.ones(pv.ntth * pv.neta).reshape(pv.shape)
    finally:
        polar_config['tth_max'] = old_tth_max
