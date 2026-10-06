import copy
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from hexrdgui import state
from hexrdgui.calibration.wppf_options_dialog import WppfOptionsDialog
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
