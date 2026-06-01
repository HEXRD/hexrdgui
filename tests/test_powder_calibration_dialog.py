"""Tests for the fixed asymmetry option in powder calibration.

The powder calibration dialog lets the user pin the pink-beam shape
(asymmetry) parameters for whichever pink-beam peak shape is selected -
alpha/beta for DCS, sigma for heating, tau for exponential - optionally
populating them from a prior WPPF refinement. A single adaptive group swaps
the shown fields to match the selected peak type. PowderRunner only forwards
them to the PowderCalibrator when the toggle is on AND the peak type is a
pink-beam profile.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from unittest import mock
from unittest.mock import MagicMock, PropertyMock

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from hexrd.material import Material

from hexrdgui.hexrd_config import HexrdConfig
import hexrdgui.calibration.auto.powder_calibration_dialog as dialog_mod
import hexrdgui.calibration.auto.powder_runner as runner_mod
from hexrdgui.calibration.auto.powder_calibration_dialog import (
    ASYMMETRY_PARAM_LABELS,
    NUM_ASYMMETRY_ROWS,
    PowderCalibrationDialog,
)
from hexrdgui.calibration.auto.powder_runner import PowderRunner

# The shape params shown for each pink-beam peak type, in order.
PINK_PARAMS: dict[str, list[str]] = {
    'pink_beam_dcs': ['alpha0', 'alpha1', 'beta0', 'beta1'],
    'pink_beam_heating': ['sigma0', 'sigma1'],
    'pink_beam_exponential': ['tau0', 'tau1', 'tau2'],
}


@pytest.fixture
def restore_calibration_config() -> Iterator[None]:
    # These tests mutate the global HexrdConfig singleton; snapshot and
    # restore the calibration subtree so they don't leak into other tests.
    calibration = HexrdConfig().config['calibration']
    saved = copy.deepcopy(calibration)
    yield
    HexrdConfig().config['calibration'] = saved


@pytest.fixture
def dialog(qtbot: QtBot, restore_calibration_config: None) -> PowderCalibrationDialog:
    material = Material()
    # Ensure a tth width is set so the dialog doesn't prompt for one.
    material.planeData.tThWidth = np.radians(0.2)
    with mock.patch.object(dialog_mod.QMessageBox, 'warning'):
        d = PowderCalibrationDialog(material)
    qtbot.addWidget(d.ui)
    return d


def test_asymmetry_group_hidden_for_non_pink(
    dialog: PowderCalibrationDialog,
) -> None:
    dialog.peak_fit_type = 'gaussian'
    assert dialog.ui.asymmetry_container.isHidden()
    assert dialog._shown_params == []


@pytest.mark.parametrize('pktype,params', list(PINK_PARAMS.items()))
def test_asymmetry_inputs_hidden_when_unchecked(
    dialog: PowderCalibrationDialog, pktype: str, params: list[str]
) -> None:
    # For a pink-beam type the checkbox stays reachable, but the inputs and
    # populate button collapse away until the box is checked.
    dialog.peak_fit_type = pktype
    dialog.use_wppf_asymmetry = False

    assert dialog.ui.use_wppf_asymmetry_check.isVisibleTo(dialog.ui)
    assert not dialog.ui.populate_from_wppf_button.isVisibleTo(dialog.ui)
    for i in range(NUM_ASYMMETRY_ROWS):
        assert not dialog.asym_value(i).isVisibleTo(dialog.ui)
        assert not dialog.asym_label(i).isVisibleTo(dialog.ui)


@pytest.mark.parametrize('pktype,params', list(PINK_PARAMS.items()))
def test_asymmetry_group_shows_correct_fields(
    dialog: PowderCalibrationDialog, pktype: str, params: list[str]
) -> None:
    dialog.peak_fit_type = pktype
    dialog.use_wppf_asymmetry = True

    assert not dialog.ui.asymmetry_container.isHidden()
    assert dialog.ui.populate_from_wppf_button.isVisibleTo(dialog.ui)
    assert dialog._shown_params == params

    for i in range(NUM_ASYMMETRY_ROWS):
        spinbox = dialog.asym_value(i)
        if i < len(params):
            assert spinbox.isVisibleTo(dialog.ui)
            expected = f'{ASYMMETRY_PARAM_LABELS[params[i]]}:'
            assert dialog.asym_label(i).text() == expected
        else:
            assert not spinbox.isVisibleTo(dialog.ui)


def test_values_preserved_across_peak_type_switch(
    dialog: PowderCalibrationDialog,
) -> None:
    dialog.peak_fit_type = 'pink_beam_dcs'
    dialog.use_wppf_asymmetry = True
    dialog.asym_value(0).setValue(99.9)  # alpha0

    # Switch away and back; the edited value must survive.
    dialog.peak_fit_type = 'pink_beam_heating'
    dialog.peak_fit_type = 'pink_beam_dcs'

    assert dialog.asym_value(0).value() == pytest.approx(99.9)


@pytest.mark.parametrize('pktype,params', list(PINK_PARAMS.items()))
def test_asymmetry_config_round_trip(
    dialog: PowderCalibrationDialog, pktype: str, params: list[str]
) -> None:
    dialog.peak_fit_type = pktype
    dialog.use_wppf_asymmetry = True
    values = {name: 1.5 + i for i, name in enumerate(params)}
    for i, name in enumerate(params):
        dialog.asym_value(i).setValue(values[name])

    dialog.update_config()

    cfg = HexrdConfig().config['calibration']['powder']['fixed_pink_asymmetry']
    assert cfg['enabled'] is True
    for name, value in values.items():
        assert cfg[name] == pytest.approx(value)
    # All param keys (every peak type) are persisted, not just the active set.
    for names in PINK_PARAMS.values():
        for name in names:
            assert name in cfg


@pytest.mark.parametrize('pktype,params', list(PINK_PARAMS.items()))
def test_populate_from_wppf_fills_values(
    dialog: PowderCalibrationDialog, pktype: str, params: list[str]
) -> None:
    expected = {name: 0.5 + i for i, name in enumerate(params)}
    HexrdConfig().config['calibration']['wppf'] = {
        'params_dict': {name: {'value': v} for name, v in expected.items()}
    }

    dialog.peak_fit_type = pktype
    dialog.use_wppf_asymmetry = True
    dialog.populate_asymmetry_from_wppf()

    for i, name in enumerate(params):
        assert dialog.asym_value(i).value() == pytest.approx(expected[name])


def test_populate_from_wppf_warns_when_missing(
    dialog: PowderCalibrationDialog,
) -> None:
    # Only one of the heating params present -> nothing populated, user warned.
    HexrdConfig().config['calibration']['wppf'] = {
        'params_dict': {'sigma0': {'value': 1.0}}
    }
    dialog.peak_fit_type = 'pink_beam_heating'
    dialog.asym_value(0).setValue(42.0)

    with mock.patch.object(dialog_mod.QMessageBox, 'warning') as warning:
        dialog.populate_asymmetry_from_wppf()

    assert warning.called
    assert dialog.asym_value(0).value() == pytest.approx(42.0)


def _run_powder_runner(enabled: bool, pk_type: str) -> dict | None:
    powder = HexrdConfig().config['calibration']['powder']
    powder['pk_type'] = pk_type
    powder['bg_type'] = 'linear'
    powder['auto_guess_initial_fwhm'] = True
    powder['fixed_pink_asymmetry'] = {
        'enabled': enabled,
        'alpha0': 11.0,
        'alpha1': 0.4,
        'beta0': 2.1,
        'beta1': -5.2,
        'sigma0': 0.3,
        'sigma1': 1.1,
        'tau0': 1.2,
        'tau1': -0.8,
        'tau2': 0.5,
    }

    overlay = MagicMock()
    overlay.refinements = []
    overlay.tth_distortion_dict = None
    overlay.xray_source = None

    runner = PowderRunner()

    dialog_cls = MagicMock()
    dialog_cls.return_value.exec.return_value = True

    with (
        mock.patch.object(runner_mod, 'PowderCalibrationDialog', dialog_cls),
        mock.patch.object(
            runner_mod, 'create_hedm_instrument', return_value=MagicMock()
        ),
        mock.patch.object(
            runner_mod, 'guess_engineering_constraints', return_value=None
        ),
        mock.patch.object(runner_mod, 'PowderCalibrator') as powder_calibrator,
        mock.patch.object(runner_mod, 'InstrumentCalibrator'),
        mock.patch.object(
            PowderRunner,
            'active_overlay',
            new_callable=PropertyMock,
            return_value=overlay,
        ),
        mock.patch.object(
            PowderRunner,
            'material',
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ),
        mock.patch.object(
            type(HexrdConfig()),
            'masked_images_dict',
            new_callable=PropertyMock,
            return_value={},
        ),
        mock.patch.object(runner, 'extract_powder_lines'),
    ):
        runner._run()
        return powder_calibrator.call_args.kwargs['fixed_pink_asymmetry']


@pytest.mark.parametrize('pktype,params', list(PINK_PARAMS.items()))
def test_runner_forwards_only_active_params(
    qtbot: QtBot,
    restore_calibration_config: None,
    pktype: str,
    params: list[str],
) -> None:
    # Enabled + a pink-beam type: only that type's params are forwarded.
    forwarded = _run_powder_runner(True, pktype)
    assert forwarded is not None
    assert set(forwarded) == set(params)


def test_runner_skips_when_disabled_or_non_pink(
    qtbot: QtBot, restore_calibration_config: None
) -> None:
    # Toggle off: nothing forwarded even for a pink-beam type.
    assert _run_powder_runner(False, 'pink_beam_dcs') is None
    # Non-pink peak type: nothing forwarded even when enabled.
    assert _run_powder_runner(True, 'gaussian') is None
