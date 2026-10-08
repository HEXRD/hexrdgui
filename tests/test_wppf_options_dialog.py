import copy
from pathlib import Path
from types import SimpleNamespace

import h5py
import lmfit
import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from hexrdgui import state
from hexrdgui.calibration import wppf_options_dialog
from hexrdgui.calibration.wppf_options_dialog import WppfOptionsDialog
from hexrdgui.calibration.wppf_runner import WppfRunner
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_canvas import ImageCanvas


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
    tmp_path: Path,
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


def test_legacy_state_file_defaults_statistical_weights_off(tmp_path: Path) -> None:
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

    num_pixels = np.ma.array([10.0, 20.0, 30.0, 40.0])
    canvas = SimpleNamespace(azimuthal_integral_num_pixels=lambda: num_pixels)
    monkeypatch.setattr(
        HexrdConfig,
        'active_canvas',
        property(lambda self: canvas),
    )

    kwargs = dialog._statistical_weights_kwargs
    assert kwargs['num_averaged_pixels'] is num_pixels

    monkeypatch.setattr(
        HexrdConfig(),
        'last_unscaled_azimuthal_integral_data',
        (np.array([1.0, 2.0, 3.0, 4.0]), np.zeros(4)),
    )
    dialog.limit_tth = True
    dialog.min_tth = 2.0
    dialog.max_tth = 3.0
    np.testing.assert_array_equal(
        dialog._statistical_weights_kwargs['num_averaged_pixels'],
        [20.0, 30.0],
    )

    dialog.use_experiment_file = True
    assert dialog._statistical_weights_kwargs == {}

    dialog.use_experiment_file = False
    dialog.use_statistical_weights = False
    assert dialog._statistical_weights_kwargs == {}


def test_azimuthal_integral_num_pixels() -> None:
    # The pixel counts must match the pixels the lineout averaged over
    pimg = np.array([[1.0, np.nan, 3.0], [5.0, np.nan, np.nan]])
    canvas = SimpleNamespace(
        unscaled_images=[pimg],
        _invalidate_skipped_detectors=lambda img: img,
    )
    num_pixels = ImageCanvas.azimuthal_integral_num_pixels(canvas)
    lineout = ImageCanvas._compute_azimuthal_integral_sum(canvas, pimg)
    np.testing.assert_array_equal(num_pixels.filled(0), [2, 0, 1])
    np.testing.assert_allclose((lineout * num_pixels)[~num_pixels.mask], [6.0, 3.0])


def test_phase_fractions(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(HexrdConfig().config['calibration'], 'wppf', {})
    names = ['Cu', 'Cu2O']
    for name in names:
        mat = copy.deepcopy(HexrdConfig().material('CeO2'))
        mat.name = name
        HexrdConfig().add_material(name, mat)

    try:
        dialog = WppfOptionsDialog()
        qtbot.addWidget(dialog.ui)
        dialog.selected_materials = names[:1]
        dialog.method = 'Rietveld'

        # Adding a phase used to keep "Cu = 1" next to the new remainder
        # "Cu2O = 1 - Cu", which pinned Cu2O at zero
        dialog.selected_materials = names
        dialog.update_params()
        cu, cu2o = (dialog.params[f'{x}_phase_fraction'] for x in names)
        assert (cu.value, cu.expr, cu2o.value) == (0.5, None, 0.5)

        # Fraction bounds are locked, but not their values
        model = dialog.tree_view.model()
        cell = ('Materials', 'Cu', 'Phase Fraction')
        assert cell + (model.MIN_IDX,) in model.uneditable_paths
        assert cell + (model.VALUE_IDX,) not in model.uneditable_paths

        # Fractions are shown and edited as percentages
        config = model.config_path(list(cell))
        assert (config['_value'], config['_max'], config['_units']) == (50, 100, '%')
        model.set_config_val(list(cell) + ['_value'], 30)
        assert cu.value == pytest.approx(0.3)

        # The remainder shows its uncertainty
        cu2o.stderr = 0.01
        result = SimpleNamespace(res=SimpleNamespace(params=dialog.params))
        monkeypatch.setattr(dialog, '_wppf_object', result)
        assert dialog._get_stderr_values() == {'Cu2O_phase_fraction': 0.01}

        # Delta boundaries skip the fractions, and a fixed fraction over 1
        # (typing a value moves the bounds) is caught before running
        dialog.delta_boundaries = True
        dialog.apply_delta_boundaries()
        assert (cu.min, cu.max) == (0, 1)
        dialog.spline_points = [[30.0, 1.0], [40.0, 1.0]]
        cu.set(value=1.5, max=1.5)
        with pytest.raises(ValueError, match='within'):
            dialog.validate()
    finally:
        HexrdConfig().remove_materials(names)


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
        'model_types': {'Ni': wppf_options_dialog.MARCH_DOLLASE_MODEL},
        'preferred_axes': {'Ni': [1, 0, -1]},
    }
    settings = dialog.texture_settings
    assert {k: settings[k] for k in expected_settings} == expected_settings
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

    monkeypatch.setattr(
        wppf_options_dialog, 'MarchDollaseModel', DummyMarchDollaseModel
    )
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
    settings = loaded_wppf['texture_settings']
    assert {k: settings[k] for k in expected_settings} == expected_settings
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


def test_march_dollase_refinement(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Refine P_MD on a pattern simulated with P_MD = 1.5
    monkeypatch.setitem(HexrdConfig().config['calibration'], 'wppf', {})
    tth = np.linspace(2, 30, 1400)

    def set_lineout(y: np.ndarray) -> None:
        data = (tth, np.ma.array(y))
        monkeypatch.setattr(
            HexrdConfig(), 'last_unscaled_azimuthal_integral_data', data
        )

    set_lineout(np.full_like(tth, 100.0))
    dialog = WppfOptionsDialog()
    qtbot.addWidget(dialog.ui)
    dialog.use_statistical_weights = False
    dialog.spline_points = [[3.0, 100.0], [29.0, 100.0]]
    dialog.selected_materials = ['CeO2']
    dialog.method = 'Rietveld'
    dialog.ui.include_texture_model.setChecked(True)
    dialog.ui.texture_model_type.setCurrentText('March-Dollase')
    dialog.ui.texture_preferred_axis_k.setValue(0)
    dialog.ui.texture_preferred_axis_l.setValue(0)
    for param in dialog.params.values():
        param.vary = False

    dialog.params['CeO2_p_md'].value = 1.5
    obj = dialog.wppf_object
    assert obj.texture_model['CeO2'].HKL.tolist() == [1, 0, 0]
    obj._set_params_vals_to_class(obj.params, force=True)
    obj.computespectrum()
    sim = obj.spectrum_sim
    set_lineout(np.interp(tth, sim.x, np.nan_to_num(sim.y)))
    dialog.reset_object()

    dialog.params['CeO2_p_md'].set(value=1.0, vary=True)
    runner = WppfRunner()
    runner.wppf_options_dialog = dialog
    dialog.run.connect(runner.run_wppf)
    dialog.begin_run()
    assert dialog.params['CeO2_p_md'].value == pytest.approx(1.5, abs=1e-3)
    assert dialog.ui.texture_index_label.text() == 'Texture index: 1.50'

    dialog.pop_undo_stack()
    assert dialog.params['CeO2_p_md'].value == 1.0



@pytest.mark.parametrize(
    'model_type', ['March-Dollase', 'General Axis Distribution Function']
)
def test_texture_model_follows_lattice_updates(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    model_type: str,
) -> None:
    # Writing refined lattice parameters back to a monoclinic material
    # reorders its hkls. The texture model must follow on the next update.
    monkeypatch.setitem(HexrdConfig().config['calibration'], 'wppf', {})
    tth = np.linspace(2, 30, 1400)
    data = (tth, np.ma.array(np.full_like(tth, 100.0)))
    monkeypatch.setattr(HexrdConfig(), 'last_unscaled_azimuthal_integral_data', data)

    name = 'U6Nb'
    HexrdConfig().load_default_material(name)
    try:
        dialog = WppfOptionsDialog()
        qtbot.addWidget(dialog.ui)
        dialog.use_statistical_weights = False
        dialog.spline_points = [[3.0, 100.0], [29.0, 100.0]]
        dialog.selected_materials = [name]
        dialog.method = 'Rietveld'
        dialog.ui.include_texture_model.setChecked(True)
        dialog.ui.texture_model_type.setCurrentText(model_type)

        old_hkls = dialog.wppf_object.texture_model[name].material.hkls
        mat = HexrdConfig().material(name)
        mat.lparms = mat.lparms * [0.99, 1, 1, 1, 1, 1]

        obj = dialog.wppf_object
        model = obj.texture_model[name]
        phase = obj.phases[name]['synchrotron']
        assert not np.array_equal(phase.hkls, old_hkls)
        assert model.material is phase
        if model_type == 'March-Dollase':
            assert len(model.texture_factors) == len(phase.hkls)

        obj.computespectrum()
    finally:
        HexrdConfig().remove_materials([name])
