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


def test_loading_state_migrates_removed_pinhole_names(qapp: QApplication) -> None:
    # State files from before the JHE model was removed use older names
    config = HexrdConfig()
    kwargs = {'pinhole_thickness': 0.075, 'pinhole_radius': 0.15}
    try:
        for old_type, new_type in [
            ('RyggPinholeDistortion', 'PinholeDistortion'),
            ('JHEPinholeDistortion', None),
        ]:
            config.custom_polar_tth_distortion_object_serialized = {
                'active': False,
                'serialized': {
                    'name': '[Custom]',
                    'pinhole_distortion_type': old_type,
                    'pinhole_distortion_kwargs': dict(kwargs),
                },
            }
            obj = config.saved_custom_polar_tth_distortion_object
            if new_type is None:
                assert obj is None
            else:
                assert obj.pinhole_distortion_type == new_type
                assert obj.has_polar_pinhole_displacement_field
    finally:
        config.custom_polar_tth_distortion_object = None
        config.saved_custom_polar_tth_distortion_object = None
