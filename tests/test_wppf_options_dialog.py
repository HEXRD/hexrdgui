from types import SimpleNamespace

import h5py
import lmfit
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


def test_march_dollase_settings_and_parameter_files(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calibration = HexrdConfig().config['calibration']
    monkeypatch.setitem(calibration, 'wppf', {})

    dialog = WppfOptionsDialog()
    qtbot.addWidget(dialog.ui)

    # The setting-change callbacks normally regenerate all WPPF parameters.
    # Keep this test focused on the texture GUI and persistence paths.
    monkeypatch.setattr(dialog, 'update_params', lambda *args, **kwargs: None)
    dialog.method = 'Rietveld'
    dialog.ui.selected_texture_material.clear()
    dialog.ui.selected_texture_material.addItem('Ni')
    dialog.ui.include_texture_model.setChecked(True)
    dialog.ui.texture_model_type.setCurrentText('March-Dollase')
    dialog.ui.texture_preferred_axis_h.setValue(1)
    dialog.ui.texture_preferred_axis_k.setValue(0)
    dialog.ui.texture_preferred_axis_l.setValue(-1)

    expected_settings = {
        'model_type': wppf_options_dialog.MARCH_DOLLASE_MODEL,
        'hkl': [1, 0, -1],
    }
    assert dialog.texture_model_kwargs['Ni'] == expected_settings
    assert dialog.ui.texture_sample_symmetry.isHidden()
    assert not dialog.ui.texture_preferred_axis_h.isHidden()
    assert not dialog.ui.texture_preferred_axis_k.isHidden()
    assert not dialog.ui.texture_preferred_axis_l.isHidden()
    assert not dialog.ui.texture_azimuthal_interval.isEnabled()
    assert not dialog.ui.texture_integration_range.isEnabled()

    constructed = {}

    class DummyMarchDollaseModel:
        def __init__(self, **kwargs):
            constructed.update(kwargs)

    monkeypatch.setattr(wppf_options_dialog, 'MarchDollaseModel', DummyMarchDollaseModel)
    monkeypatch.setattr(
        wppf_options_dialog,
        'Material_Rietveld',
        lambda material_obj: f'rietveld-{material_obj}',
    )
    monkeypatch.setattr(HexrdConfig, 'material', lambda self, name: name)
    assert isinstance(dialog.texture_model_dict['Ni'], DummyMarchDollaseModel)
    assert constructed == {'material': 'rietveld-Ni', 'HKL': [1, 0, -1]}

    dialog.params = lmfit.Parameters()
    dialog.params.add('Ni_p_md', value=1.25, min=0.0, vary=True)
    tree = dialog.tree_view_dict_of_params
    assert tree['Texture']['Ni']['P_md']['_param'] is dialog.params['Ni_p_md']

    params_file = tmp_path / 'params.h5'
    dialog.save_params(params_file)
    dialog.params['Ni_p_md'].value = 2.0
    dialog.load_params(params_file)
    assert dialog.params['Ni_p_md'].value == pytest.approx(1.25)

    dialog.save_settings()
    state_file = tmp_path / 'state.h5'
    snapshot = {'config_calibration': {'wppf': calibration['wppf']}}
    with h5py.File(state_file, 'w') as f:
        state._save_config(f, snapshot)
    with h5py.File(state_file, 'r') as f:
        loaded = state._load_config(f)

    loaded_wppf = loaded['config_calibration']['wppf']
    assert loaded_wppf['texture_settings']['model_kwargs']['Ni'] == expected_settings
    assert loaded_wppf['params_dict']['Ni_p_md']['value'] == pytest.approx(1.25)


def test_saved_plot_contains_march_dollase_parameter(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calibration = HexrdConfig().config['calibration']
    monkeypatch.setitem(calibration, 'wppf', {})

    dialog = WppfOptionsDialog()
    qtbot.addWidget(dialog.ui)
    dialog.params = lmfit.Parameters()
    dialog.params.add('Ni_p_md', value=1.25)
    dialog._wppf_object = SimpleNamespace(
        spectrum_sim=SimpleNamespace(x=np.arange(3), y=np.arange(3)),
        weights=SimpleNamespace(y=np.ones(3)),
        background=SimpleNamespace(y=np.zeros(3)),
        amorphous_model=None,
    )
    monkeypatch.setattr(
        HexrdConfig(),
        'last_unscaled_azimuthal_integral_data',
        (np.arange(3), np.ma.array(np.arange(3))),
    )

    output = tmp_path / 'plot.h5'
    dialog.write_data(output)

    with h5py.File(output, 'r') as f:
        assert f['params/Ni_p_md/value'][()] == pytest.approx(1.25)
