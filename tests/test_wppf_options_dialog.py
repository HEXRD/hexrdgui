import copy
from types import SimpleNamespace

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

        # The remainder shows its uncertainty
        cu2o.stderr = 0.01
        result = SimpleNamespace(res=SimpleNamespace(params=dialog.params))
        monkeypatch.setattr(dialog, '_wppf_object', result)
        assert dialog._get_stderr_values() == {'Cu2O_phase_fraction': 0.01}

        # Delta boundaries skip the fractions, and a fixed fraction over 1
        # (typing a value moves the bounds) is caught before running
        cu.value = 0.3
        dialog.delta_boundaries = True
        dialog.apply_delta_boundaries()
        assert (cu.min, cu.max) == (0, 1)
        dialog.spline_points = [[30.0, 1.0], [40.0, 1.0]]
        cu.set(value=1.5, max=1.5)
        with pytest.raises(ValueError, match='within'):
            dialog.validate()
    finally:
        HexrdConfig().remove_materials(names)
