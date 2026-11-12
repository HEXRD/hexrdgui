from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSettings
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


def test_settings_restore_single_item_lists(qapp: QApplication, tmp_path: Path) -> None:
    # How QSettings writes ['viridis'] and [] to an ini file. On reading, a
    # one-item list comes back as a str and an empty list as None.
    path = tmp_path / 'settings.ini'
    path.write_text(
        '[General]\n'
        'limited_cmaps_list=viridis\n'
        '_imported_default_materials=@Invalid()\n'
    )
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    state = HexrdConfig()._load_state_from_settings(settings)
    assert state['limited_cmaps_list'] == ['viridis']
    assert state['_imported_default_materials'] == []
