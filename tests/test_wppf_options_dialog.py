from types import SimpleNamespace

import h5py
import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from hexrdgui import state
import hexrdgui.calibration.wppf_options_dialog as wppf_options_dialog
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


def test_statistical_weights_are_enabled_by_default(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calibration = HexrdConfig().config['calibration']
    monkeypatch.setitem(calibration, 'wppf', {})

    dialog = WppfOptionsDialog()
    qtbot.addWidget(dialog.ui)

    assert dialog.use_statistical_weights
    assert 'χ²' in dialog.ui.use_statistical_weights.toolTip()


@pytest.mark.parametrize('selected', [True, False])
def test_statistical_weights_survive_state_file_round_trip(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    selected: bool,
) -> None:
    calibration = HexrdConfig().config['calibration']
    monkeypatch.setitem(calibration, 'wppf', {})

    first = WppfOptionsDialog()
    qtbot.addWidget(first.ui)
    first.use_statistical_weights = selected
    first.save_settings()

    state_file = tmp_path / 'state.h5'
    snapshot = {
        'config_calibration': {
            'wppf': {
                'use_statistical_weights': calibration['wppf'][
                    'use_statistical_weights'
                ],
            },
        },
    }
    with h5py.File(state_file, 'w') as f:
        state._save_config(f, snapshot)
    with h5py.File(state_file, 'r') as f:
        loaded = state._load_config(f)

    monkeypatch.setitem(
        HexrdConfig().config,
        'calibration',
        loaded['config_calibration'],
    )
    second = WppfOptionsDialog()
    qtbot.addWidget(second.ui)

    assert loaded['config_calibration']['wppf']['use_statistical_weights'] is selected
    assert second.use_statistical_weights is selected


def test_legacy_state_file_defaults_statistical_weights_off(tmp_path) -> None:
    state_file = tmp_path / 'legacy_state.h5'
    snapshot = {'config_calibration': {'wppf': {}}}
    with h5py.File(state_file, 'w') as f:
        state._save_config(f, snapshot)
    with h5py.File(state_file, 'r') as f:
        loaded = state._load_config(f)

    assert loaded['config_calibration']['wppf']['use_statistical_weights'] is False


def test_statistical_weights_kwargs(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calibration = HexrdConfig().config['calibration']
    monkeypatch.setitem(calibration, 'wppf', {})

    dialog = WppfOptionsDialog()
    qtbot.addWidget(dialog.ui)

    display_img = np.zeros((2, 4))
    canvas = SimpleNamespace(iviewer=SimpleNamespace(display_img=display_img))
    monkeypatch.setattr(
        HexrdConfig,
        'active_canvas',
        property(lambda self: canvas),
    )

    n_sampling = np.ma.array([10.0, 20.0, 30.0, 40.0])
    monkeypatch.setattr(
        wppf_options_dialog,
        'N_valid',
        lambda image: n_sampling,
    )

    kwargs = dialog._statistical_weights_kwargs
    assert kwargs['N_sampling'] is n_sampling

    monkeypatch.setattr(
        HexrdConfig(),
        'last_unscaled_azimuthal_integral_data',
        (np.array([1.0, 2.0, 3.0, 4.0]), np.zeros(4)),
    )
    dialog.limit_tth = True
    dialog.min_tth = 2.0
    dialog.max_tth = 3.0
    np.testing.assert_array_equal(
        dialog._statistical_weights_kwargs['N_sampling'],
        [20.0, 30.0],
    )

    dialog.use_statistical_weights = False
    assert dialog._statistical_weights_kwargs == {}
