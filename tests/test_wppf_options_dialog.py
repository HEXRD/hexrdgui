import pytest
from pytestqt.qtbot import QtBot

from hexrdgui.calibration.wppf_options_dialog import WppfOptionsDialog
from hexrdgui.hexrd_config import HexrdConfig


def test_amorphous_parameters_survive_settings_reload(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calibration = HexrdConfig().config['calibration']
    monkeypatch.setitem(calibration, 'wppf', {})

    first = WppfOptionsDialog()
    qtbot.addWidget(first.ui)
    first.amorphous_model = 'Split Pseudo-Voigt'
    first.num_amorphous_peaks = 2
    first.amorphous_expt_smoothing = 17
    first.include_amorphous = True

    param_name = 'peak_2_amorphous_fwhm_g_r'
    first.params[param_name].value = 8.25
    first.save_settings()

    second = WppfOptionsDialog()
    qtbot.addWidget(second.ui)

    assert second.include_amorphous
    assert second.amorphous_model == 'Split Pseudo-Voigt'
    assert second.num_amorphous_peaks == 2
    assert second.amorphous_expt_smoothing == 17
    assert second.params[param_name].value == pytest.approx(8.25)
