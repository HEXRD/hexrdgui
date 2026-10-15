import h5py
import yaml

from PySide6.QtWidgets import QApplication

from hexrdgui import state
from hexrdgui.constants import OverlayType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays.laue_overlay import LaueRangeShape


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
