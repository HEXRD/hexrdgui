"""
Test the SpotDiagnosticsDialog integration with fit_grains spots data.

Exercises:
  1. Run fit_grains with return_pull_spots_data=True on NIST ruby example
  2. Extract angles and XY data from spots
  3. Create and interact with SpotDiagnosticsDialog
  4. Verify all quantity/detector/grain selection modes render without error

Run with:
    cd hexrdgui/tests && QT_QPA_PLATFORM=offscreen python -m pytest test_spot_diagnostics.py -v -s
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from hexrd.hedm import config
from hexrd.hedm.fitgrains import fit_grains

from hexrdgui.calibration.hedm.spot_diagnostics_dialog import (
    QUANTITY_CONFIG,
    SpotDiagnosticsDialog,
)
from hexrdgui.utils.spots import extract_spot_angles, extract_spot_xyo


@pytest.fixture
def single_ge_path(example_repo_path: Path) -> Path:
    return example_repo_path / 'NIST_ruby' / 'single_GE'


@pytest.fixture
def fit_grains_with_spots(single_ge_path: Path) -> tuple[Any, list, dict]:
    """Run fit_grains and return (instrument, fit_results, spots_data)."""
    include_path = single_ge_path / 'include'
    config_path = include_path / 'ruby_config.yml'
    grains_path = single_ge_path / 'results' / 'ruby-b035e' / 'scan-0' / 'grains.out'

    os.chdir(str(include_path))

    cfg = config.open(config_path)[0]
    cfg.working_dir = str(include_path)
    grains_table = np.loadtxt(str(grains_path), ndmin=2)

    fit_results, spots_data = fit_grains(
        cfg,
        grains_table,
        write_spots_files=False,
        return_pull_spots_data=True,
    )

    instr = cfg.instrument.hedm
    return instr, fit_results, spots_data


def test_extract_spot_angles(
    fit_grains_with_spots: tuple[Any, list, dict],
) -> None:
    """Verify extract_spot_angles returns valid angular data."""
    instr, fit_results, spots_data = fit_grains_with_spots
    grain_ids = sorted(spots_data.keys())

    pred_angs, meas_angs = extract_spot_angles(spots_data, instr, grain_ids)

    det_keys = list(instr.detectors)
    assert set(pred_angs.keys()) == set(det_keys)
    assert set(meas_angs.keys()) == set(det_keys)

    for det_key in det_keys:
        assert len(pred_angs[det_key]) == len(grain_ids)
        assert len(meas_angs[det_key]) == len(grain_ids)

        for i in range(len(grain_ids)):
            p = pred_angs[det_key][i]
            m = meas_angs[det_key][i]
            assert p.ndim == 2 and p.shape[1] == 3
            assert m.ndim == 2 and m.shape[1] == 3
            assert p.shape[0] == m.shape[0]
            assert p.shape[0] > 0, 'Expected at least some valid spots'


def test_extract_spot_xyo(
    fit_grains_with_spots: tuple[Any, list, dict],
) -> None:
    """Verify extract_spot_xyo returns valid XY+omega data."""
    instr, fit_results, spots_data = fit_grains_with_spots
    grain_ids = sorted(spots_data.keys())

    xyo_pred, xyo_det = extract_spot_xyo(spots_data, instr, grain_ids)

    det_keys = list(instr.detectors)
    assert set(xyo_pred.keys()) == set(det_keys)
    assert set(xyo_det.keys()) == set(det_keys)

    for det_key in det_keys:
        assert len(xyo_pred[det_key]) == len(grain_ids)
        assert len(xyo_det[det_key]) == len(grain_ids)

        for i in range(len(grain_ids)):
            p = xyo_pred[det_key][i]
            m = xyo_det[det_key][i]
            assert p.ndim == 2 and p.shape[1] == 3
            assert m.ndim == 2 and m.shape[1] == 3
            assert p.shape[0] == m.shape[0]
            assert p.shape[0] > 0


def test_spot_diagnostics_dialog(
    qtbot: Any,
    fit_grains_with_spots: tuple[Any, list, dict],
) -> None:
    """Create SpotDiagnosticsDialog with real fit_grains data and exercise it."""
    instr, fit_results, spots_data = fit_grains_with_spots
    grain_ids = sorted(spots_data.keys())

    dialog = SpotDiagnosticsDialog(
        instr=instr,
        spots_data=spots_data,
        grain_ids=grain_ids,
    )
    qtbot.addWidget(dialog.ui)

    # The dialog should have rendered the initial canvas
    assert dialog.fig is not None
    assert dialog.canvas is not None

    det_keys = list(instr.detectors)

    # Verify combo boxes are populated
    assert dialog.ui.quantity.count() == len(QUANTITY_CONFIG)
    assert dialog.ui.detector.count() == len(det_keys)
    assert dialog.ui.grain_id.count() == len(grain_ids)

    # Exercise every quantity selection to ensure no rendering errors
    for i in range(dialog.ui.quantity.count()):
        dialog.ui.quantity.setCurrentIndex(i)
        QApplication.processEvents()

    # Toggle "show all grains"
    dialog.ui.show_all_grains.setChecked(True)
    QApplication.processEvents()
    dialog.ui.show_all_grains.setChecked(False)
    QApplication.processEvents()

    # Toggle "show all detectors" (single detector, but still exercise it)
    dialog.ui.show_all_detectors.setChecked(True)
    QApplication.processEvents()
    dialog.ui.show_all_detectors.setChecked(False)
    QApplication.processEvents()

    # Toggle "match detector shape"
    dialog.ui.match_detector_shape.setChecked(True)
    QApplication.processEvents()
    dialog.ui.match_detector_shape.setChecked(False)
    QApplication.processEvents()

    # Change histogram bins
    dialog.ui.histogram_bins.setValue(30)
    QApplication.processEvents()

    # Change bounds
    dialog.ui.bounds.setValue(0.05)
    QApplication.processEvents()
