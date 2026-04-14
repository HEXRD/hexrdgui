"""
Test that the Save Images dialog writes group-level (monolithic) images
when the instrument has ROI-based detector groups, rather than individual
sub-panel images.

Uses the same Dexelas HEDM state file and NPZ images as the workflow test.

Run with:
    cd hexrdgui/tests && python -m pytest test_save_images.py -v -s
"""

from unittest.mock import patch

import numpy as np
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog

import hexrd.imageseries

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.save_images_dialog import SaveImagesDialog

from utils import select_files_when_asked


@pytest.fixture
def dexelas_hedm_path(example_repo_path):
    return example_repo_path / 'state_examples' / 'Dexelas_HEDM'


def _load_dexelas_state_and_images(qtbot, main_window, dexelas_hedm_path):
    """Load the ROI Dexelas state file and its two NPZ images."""
    state_file = dexelas_hedm_path / 'roi_dexelas_hedm.h5'
    npz1 = dexelas_hedm_path / 'mruby-0129_000004_ff1_000012-cachefile.npz'
    npz2 = dexelas_hedm_path / 'mruby-0129_000004_ff2_000012-cachefile.npz'

    for p in (state_file, npz1, npz2):
        assert p.exists(), f'Missing test file: {p}'

    main_window.load_state_file(state_file)
    QApplication.processEvents()

    load_panel = main_window.simple_image_series_dialog
    with select_files_when_asked([str(npz1), str(npz2)]):
        qtbot.mouseClick(load_panel.ui.image_files, Qt.MouseButton.LeftButton)

    qtbot.mouseClick(load_panel.ui.read, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def test_save_images_writes_group_files(
    qtbot, main_window, dexelas_hedm_path, tmp_path
):
    _load_dexelas_state_and_images(qtbot, main_window, dexelas_hedm_path)

    # Verify ROI setup: 8 sub-panel detectors in 2 groups
    assert len(HexrdConfig().detector_names) == 8
    assert HexrdConfig().instrument_has_roi
    group_names = HexrdConfig().detector_group_names
    assert set(group_names) == {'ff1', 'ff2'}

    # Record the sub-panel image shape for comparison
    ims_dict = HexrdConfig().imageseries_dict
    first_subpanel = HexrdConfig().detectors_in_group('ff1')[0]
    subpanel_shape = ims_dict[first_subpanel][0].shape

    # Create the dialog and verify the combo shows group names
    HexrdConfig().set_images_dir(str(tmp_path))
    dialog = SaveImagesDialog(main_window.ui)

    combo_items = [
        dialog.ui.detectors.itemText(i)
        for i in range(dialog.ui.detectors.count())
    ]
    assert set(combo_items) == {'ff1', 'ff2'}, (
        f'Expected group names in combo, got: {combo_items}'
    )

    # Configure the dialog for NPZ output
    dialog.ui.file_stem.setText('test')
    npz_index = dialog.ui.format.findText('npz')
    dialog.ui.format.setCurrentIndex(npz_index)

    # Mock the threshold dialog to auto-return 0
    with patch.object(
        QInputDialog, 'getDouble', return_value=(0.0, True)
    ):
        dialog.save_images()

    QApplication.processEvents()

    # Verify that only group-level files were created (not sub-panel files)
    npz_files = sorted(tmp_path.glob('*.npz'))
    npz_names = [f.name for f in npz_files]
    assert set(npz_names) == {'test_ff1.npz', 'test_ff2.npz'}, (
        f'Expected 2 group files, got: {npz_names}'
    )

    # Load the saved images and verify they are monolithic (larger than
    # sub-panel images)
    for npz_file in npz_files:
        saved_ims = hexrd.imageseries.open(
            str(npz_file), 'frame-cache', style='npz'
        )
        saved_shape = saved_ims[0].shape
        assert saved_shape != subpanel_shape, (
            f'{npz_file.name}: shape {saved_shape} matches sub-panel '
            f'shape -- expected monolithic (larger) image'
        )
        # Monolithic image should be larger in at least one dimension
        assert (
            saved_shape[0] >= subpanel_shape[0]
            and saved_shape[1] >= subpanel_shape[1]
        ), (
            f'{npz_file.name}: saved shape {saved_shape} is not larger '
            f'than sub-panel shape {subpanel_shape}'
        )

    # Also verify the saved images match the originals
    npz1 = dexelas_hedm_path / 'mruby-0129_000004_ff1_000012-cachefile.npz'
    npz2 = dexelas_hedm_path / 'mruby-0129_000004_ff2_000012-cachefile.npz'
    for group, orig_npz in [('ff1', npz1), ('ff2', npz2)]:
        orig_ims = hexrd.imageseries.open(
            str(orig_npz), 'frame-cache', style='npz'
        )
        saved_ims = hexrd.imageseries.open(
            str(tmp_path / f'test_{group}.npz'), 'frame-cache', style='npz'
        )
        assert orig_ims[0].shape == saved_ims[0].shape, (
            f'{group}: original shape {orig_ims[0].shape} != '
            f'saved shape {saved_ims[0].shape}'
        )
        assert len(saved_ims) == len(orig_ims), (
            f'{group}: frame count {len(saved_ims)} != {len(orig_ims)}'
        )
        # Verify first and last frame values are close
        np.testing.assert_allclose(
            saved_ims[0], orig_ims[0], atol=1,
            err_msg=f'{group}: first frame values differ',
        )
        np.testing.assert_allclose(
            saved_ims[-1], orig_ims[-1], atol=1,
            err_msg=f'{group}: last frame values differ',
        )
