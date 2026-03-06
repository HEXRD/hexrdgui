"""
Full HEDM workflow integration test.

Exercises the complete pipeline:
  1. Load state file (roi_dexelas_hedm.h5)
  2. Load NPZ images
  3. Run indexing (generate eta-omega maps, find orientations, cluster)
  4. Verify indexing results (3 grains)
  5. Run fit grains with min structure factor filtering
  6. Verify fit grains results
  7. Export grains table and workflow
  8. Run CLI hexrd fit-grains on exported workflow
  9. Compare GUI and CLI results

Run with:
    cd hexrdgui/tests && python -m pytest test_hedm_workflow.py -v -s
"""

import subprocess
from pathlib import Path

import numpy as np
import pytest
import yaml

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from hexrdgui.hexrd_config import HexrdConfig

from utils import select_files_when_asked


@pytest.fixture
def dexelas_hedm_path(example_repo_path):
    return example_repo_path / 'state_examples' / 'Dexelas_HEDM'


def test_hedm_full_workflow(qtbot, main_window, dexelas_hedm_path, tmp_path):
    # ── paths ──────────────────────────────────────────────────────────
    state_file = dexelas_hedm_path / 'roi_dexelas_hedm.h5'
    npz1 = dexelas_hedm_path / 'mruby-0129_000004_ff1_000012-cachefile.npz'
    npz2 = dexelas_hedm_path / 'mruby-0129_000004_ff2_000012-cachefile.npz'

    for p in (state_file, npz1, npz2):
        assert p.exists(), f'Missing test file: {p}'

    # ── Step A: load state file ────────────────────────────────────────
    main_window.load_state_file(state_file)
    QApplication.processEvents()

    # Verify detectors were loaded (ROI config has 8 sub-panel detectors)
    detectors = HexrdConfig().detectors
    assert len(detectors) == 8

    # Override working_dir so it exists in CI
    HexrdConfig().working_dir = str(tmp_path)
    HexrdConfig().indexing_config['working_dir'] = str(tmp_path)

    # ── Step B: load NPZ images ────────────────────────────────────────
    def is_dummy_data():
        for ims in HexrdConfig().imageseries_dict.values():
            if len(ims) != 1 or not np.all(ims[0] == 1):
                return False
        return True

    assert is_dummy_data()

    load_panel = main_window.simple_image_series_dialog
    with select_files_when_asked([str(npz1), str(npz2)]):
        qtbot.mouseClick(load_panel.ui.image_files, Qt.LeftButton)

    qtbot.mouseClick(load_panel.ui.read, Qt.LeftButton)
    QApplication.processEvents()

    assert not is_dummy_data()

    # ── Step C: trigger indexing ───────────────────────────────────────
    main_window.on_action_run_indexing_triggered()
    runner = main_window._indexing_runner

    # ── Step D: accept OmeMapsSelectDialog (generate maps) ─────────────
    dialog = runner.ome_maps_select_dialog
    assert dialog is not None
    # The state file should have set method to 'generate'
    assert dialog.method_name == 'generate'
    dialog.ui.accept()

    # After accept, ome maps are generated asynchronously via
    # progress_dialog.exec() which runs a nested event loop.
    # When the worker finishes, the progress dialog closes, and
    # view_ome_maps() is called, creating OmeMapsViewerDialog.
    QApplication.processEvents()

    # ── Step E: accept OmeMapsViewerDialog (run find-orientations) ─────
    dialog = runner.ome_maps_viewer_dialog
    assert dialog is not None
    dialog.ui.accept()

    # This triggers fiber generation, paintGrid, clustering via
    # progress_dialog.exec().  When done, confirm_indexing_results()
    # creates IndexingResultsDialog.
    QApplication.processEvents()

    # ── Step F: verify indexing results ────────────────────────────────
    assert runner.grains_table is not None
    num_grains = runner.grains_table.shape[0]
    print(f'\nIndexing found {num_grains} grains')
    assert num_grains == 3, f'Expected 3 grains, got {num_grains}'

    # Print grain orientations for reference
    for grain in runner.grains_table:
        print(f'  grain {int(grain[0])}: exp_map_c = {grain[3:6]}')

    # ── Step G: accept IndexingResultsDialog → start fit grains ────────
    indexing_dialog = runner.indexing_results_dialog
    assert indexing_dialog is not None
    indexing_dialog.ui.accept()
    QApplication.processEvents()

    fit_runner = runner._fit_grains_runner
    assert fit_runner is not None

    # ── Step H: configure FitGrainsOptionsDialog ───────────────────────
    options_dialog = fit_runner.fit_grains_options_dialog
    assert options_dialog is not None

    # Apply minimum structure factor threshold of 5
    options_dialog.ui.min_sfac_value.setValue(5.0)
    options_dialog.apply_min_sfac_to_hkls()
    QApplication.processEvents()

    # ── Step I: click "Fit Grains" (accept options dialog) ─────────────
    # Applying min sfac excludes [0,0,6] which was an active HKL.
    # validate() will show a QMessageBox.critical() informing the user
    # that it will re-enable those HKLs.  Auto-close it.
    def close_active_hkl_warning():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMessageBox):
                w.accept()
                return
        # If not found yet, try again shortly
        QTimer.singleShot(50, close_active_hkl_warning)

    QTimer.singleShot(0, close_active_hkl_warning)
    options_dialog.ui.accept()

    # fit_grains runs asynchronously via progress_dialog.exec().
    # On completion, fit_grains_finished() → view_fit_grains_results()
    QApplication.processEvents()

    # ── Step J: verify fit grains results ──────────────────────────────
    gui_grains_table = fit_runner.result_grains_table
    assert gui_grains_table is not None
    assert gui_grains_table.shape[0] == 3
    assert gui_grains_table.shape[1] == 21

    print('\nFit grains results:')
    for grain in gui_grains_table:
        print(f'  grain {int(grain[0])}:')
        print(f'    completeness = {grain[1]:.4f}')
        print(f'    chi2         = {grain[2]:.6f}')
        print(f'    exp_map_c    = {grain[3:6]}')
        print(f'    tvec         = {grain[6:9]}')

    # Basic sanity checks
    completeness = gui_grains_table[:, 1]
    assert np.all(completeness > 0), 'All completeness values should be > 0'

    chi_squared = gui_grains_table[:, 2]
    assert np.all(chi_squared >= 0), 'All chi2 values should be >= 0'

    # ── Step K: export grains table ────────────────────────────────────
    results_dialog = fit_runner.fit_grains_results_dialog
    assert results_dialog is not None

    grains_out_path = tmp_path / 'gui_grains.out'
    with select_files_when_asked(str(grains_out_path)):
        results_dialog.on_export_button_pressed()

    assert grains_out_path.exists(), 'Grains export file was not created'
    gui_grains_from_file = np.loadtxt(str(grains_out_path), ndmin=2)
    # Text serialization introduces small rounding (up to ~1e-6)
    np.testing.assert_allclose(gui_grains_from_file, gui_grains_table, atol=1e-6)

    # ── Step L: export full workflow ───────────────────────────────────
    workflow_dir = tmp_path / 'workflow'
    workflow_dir.mkdir()
    with select_files_when_asked(str(workflow_dir)):
        results_dialog.on_export_workflow_clicked()

    QApplication.processEvents()

    # Verify expected workflow files exist
    expected_files = ['workflow.yml', 'materials.h5', 'instrument.hexrd']
    for f in expected_files:
        assert (workflow_dir / f).exists(), f'Missing workflow file: {f}'

    # At least some detector NPZ files should be exported
    det_npz_files = list(workflow_dir.glob('*.npz'))
    assert len(det_npz_files) > 0, 'No detector NPZ files were exported'

    # ── Step M: modify workflow.yml to point to original images ────────
    # The exported workflow already uses group-level entries (ff1, ff2)
    # with ROIs preserved in the instrument config.  Just update the
    # file paths from the exported NPZs to the original monolith files.
    with open(workflow_dir / 'workflow.yml') as f:
        config = yaml.safe_load(f)

    group_to_npz = {
        'ff1': str(npz1),
        'ff2': str(npz2),
    }
    for entry in config['image_series']['data']:
        panel = entry['panel']
        entry['file'] = group_to_npz[panel]

    with open(workflow_dir / 'workflow.yml', 'w') as f:
        yaml.dump(config, f)

    # ── Step N: run CLI hexrd fit-grains ───────────────────────────────
    result = subprocess.run(
        ['hexrd', 'fit-grains', str(workflow_dir / 'workflow.yml')],
        cwd=str(workflow_dir),
        capture_output=True,
        text=True,
        timeout=600,
    )

    print('\nhexrd fit-grains stdout:')
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.returncode != 0:
        print('hexrd fit-grains stderr:')
        print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)
    assert result.returncode == 0, (
        f'hexrd fit-grains failed with return code {result.returncode}'
    )

    # ── Step O: parse CLI output and compare with GUI export ───────────
    # Find the grains.out produced by the CLI
    cli_grains_out = find_grains_out(workflow_dir)
    assert cli_grains_out is not None, f'Could not find grains.out in {workflow_dir}'

    cli_grains = np.loadtxt(str(cli_grains_out), ndmin=2)
    assert cli_grains.shape[0] == gui_grains_from_file.shape[0], (
        f'CLI found {cli_grains.shape[0]} grains, '
        f'GUI found {gui_grains_from_file.shape[0]}'
    )

    # Sort both by grain ID for stable comparison
    gui_sorted = gui_grains_from_file[gui_grains_from_file[:, 0].argsort()]
    cli_sorted = cli_grains[cli_grains[:, 0].argsort()]

    # Compare all columns except grain ID (col 0)
    np.testing.assert_allclose(
        cli_sorted[:, 1:],
        gui_sorted[:, 1:],
        atol=1e-4,
        err_msg='CLI and GUI fit-grains results differ beyond tolerance',
    )
    print('\nCLI and GUI results match within tolerance!')


def find_grains_out(base_dir):
    """Search for grains.out file produced by hexrd CLI."""
    # hexrd writes to working_dir/analysis_name/grains.out
    for grains_file in Path(base_dir).rglob('grains.out'):
        return grains_file

    return None
