from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from hexrdgui.hexrd_config import HexrdConfig


def test_loading_state_clears_custom_polar_distortion(qapp: QApplication) -> None:
    config = HexrdConfig()
    previous = SimpleNamespace(name='previous session')
    config.custom_polar_tth_distortion_object = previous
    try:
        # A state with no custom distortion should clear the active one
        config.custom_polar_tth_distortion_object_serialized = None
        assert config.custom_polar_tth_distortion_object is None
        assert config.polar_tth_distortion_object is not previous
    finally:
        config.custom_polar_tth_distortion_object = None
        config.saved_custom_polar_tth_distortion_object = None
