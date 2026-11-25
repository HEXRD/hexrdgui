from pathlib import Path
from typing import Any

import numpy as np
import pytest

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import hexrdgui.hexrd_config
from hexrdgui.hexrd_config import HexrdConfig


def test_settings_store_numpy_without_pickling(
    qapp: QApplication, tmp_path: Path
) -> None:
    # PySide6 >= 6.12 cannot load pickled numpy objects from QSettings
    path = str(tmp_path / 'settings.ini')
    buffer = np.ones((4, 5), dtype=bool)
    buffer[0] = False
    state = {
        'sample_tilt': np.array([0.1, -0.2, 0.3]),
        'config_instrument': {
            'detectors': {'det': {'buffer': buffer, 'distance': np.float64(1.5)}},
        },
    }

    config = HexrdConfig()
    settings = QSettings(path, QSettings.Format.IniFormat)
    config._save_state_to_settings(state, settings)
    settings.sync()
    assert b'PyObject' not in Path(path).read_bytes()

    loaded = config._load_state_from_settings(settings)
    np.testing.assert_array_equal(loaded['sample_tilt'], state['sample_tilt'])
    det = loaded['config_instrument']['detectors']['det']
    assert det['buffer'].dtype == bool
    np.testing.assert_array_equal(det['buffer'], buffer)
    assert det['distance'] == 1.5


def test_settings_that_fail_to_load_are_ignored(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('settings_version', 1)
    monkeypatch.setattr(hexrdgui.hexrd_config, 'QSettings', lambda: settings)

    def fail(settings: Any) -> dict[str, Any]:
        raise RuntimeError('Failed to deserialize Python object')

    config = HexrdConfig()
    monkeypatch.setattr(config, '_load_state_from_settings', fail)

    # This must not raise, and the reason is printed once events run
    config.load_settings()
    qapp.processEvents()
    assert 'Settings could not be loaded' in capsys.readouterr().out
