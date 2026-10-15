import h5py
import numpy as np
import pytest
import yaml

from PySide6.QtWidgets import QApplication

from hexrd.utils.hkl import hkl_to_str

from hexrdgui import state
from hexrdgui.calibration.hkl_picks_tree_view_dialog import (
    picks_angles_to_cartesian,
    picks_cartesian_to_angles,
)
from hexrdgui.constants import OverlayType, ViewType
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays.laue_overlay import LaueOverlay, LaueRangeShape
from hexrdgui.overlays.powder_overlay import PowderOverlay


@pytest.fixture
def instrument(qapp, default_config_path):
    config = HexrdConfig()
    config.load_instrument_config(str(default_config_path))
    # A stage translation moves the polar view origin away from zero
    path = ['oscillation_stage', 'translation']
    config.set_instrument_config_val(path, [0.0, 2.0, 0.0])
    yield create_hedm_instrument()
    config.set_instrument_config_val(path, [0.0, 0.0, 0.0])


def test_laue_overlay_state_round_trip(main_window, default_config_path, tmp_path):
    config = HexrdConfig()
    config.load_instrument_config(str(default_config_path))
    config.overlays = []
    config.append_overlay(config.active_material_name, OverlayType.laue)
    config.overlays[0].width_shape = LaueRangeShape.rectangle

    path = tmp_path / 'state.h5'
    with h5py.File(path, 'w') as f:
        state.save(f)

    config.overlays = []
    main_window.load_state_file(path)
    QApplication.processEvents()
    assert config.overlays[0].width_shape == LaueRangeShape.rectangle

    # Older versions wrote the enums as python objects
    tag = '!!python/object/apply:hexrdgui.overlays.laue_overlay.LaueRangeShape'
    assert yaml.load(f'{tag} [rectangle]', Loader=state.H5StateLoader) == 'rectangle'


def test_polar_picks_use_stage_translation(instrument):
    det_key, panel = next(iter(instrument.detectors.items()))
    material = HexrdConfig().active_material_name

    def tth(xys):
        angs, _ = panel.cart_to_angles(np.atleast_2d(xys), tvec_s=instrument.tvec)
        return np.degrees(angs[:, 0])

    overlay = PowderOverlay(material)
    overlay.instrument = instrument
    overlay.display_mode = ViewType.polar
    ring = np.asarray(overlay.data[det_key]['rings'][0])
    ring = ring[~np.isnan(ring[:, 0])]
    hkl = hkl_to_str(overlay.data[det_key]['hkls'][0])

    # Picks on a polar ring must keep their two theta in both directions
    # (to within the inexact inverse of the GE_41RT distortion)
    overlay.calibration_picks_polar = {det_key: {hkl: ring.tolist()}}
    xys = overlay.calibration_picks[det_key][hkl]
    assert np.allclose(tth(xys), ring[:, 0], atol=1e-3)
    assert np.allclose(overlay.calibration_picks_polar[det_key][hkl], ring)

    # The picks tree editor must convert the same way
    polar = picks_cartesian_to_angles({'powder': {det_key: {hkl: xys}}})
    assert np.allclose(polar['powder'][det_key][hkl], ring)
    cart = picks_angles_to_cartesian(polar)
    assert np.allclose(cart['powder'][det_key][hkl], xys)

    params = [0.66, -0.98, 0.73, 0, 0, 0, 1, 1, 1, 0, 0, 0]
    overlay = LaueOverlay(
        material, crystal_params=params, min_energy=30, max_energy=150
    )
    overlay.instrument = instrument
    overlay.display_mode = ViewType.polar
    spot = list(overlay.data[det_key]['spots'][0])
    hkl = hkl_to_str(overlay.data[det_key]['hkls'][0])

    overlay.calibration_picks_polar = {det_key: {hkl: spot}}
    xy = overlay.calibration_picks[det_key][hkl]
    assert np.allclose(tth(xy), spot[0], atol=1e-3)
