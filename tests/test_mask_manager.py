import h5py
import numpy as np
import pytest

from hexrdgui.masking.constants import MaskType
from hexrdgui.masking.mask_manager import MaskManager, RegionMask, ThresholdMask


@pytest.fixture
def mask_manager(qtbot):
    # MaskManager is a process-wide singleton, so restore its masks after
    mm = MaskManager()
    original = mm.masks
    mm.masks = {}
    yield mm
    mm.masks = original


def add_masks(mm):
    threshold = ThresholdMask('threshold', MaskType.threshold)
    threshold.data = [0.0, 10.0]
    region = RegionMask('region', MaskType.region)
    region.data = [('ge1', np.array([[0, 0], [1, 0], [1, 1]]))]
    mm.masks = {'threshold': threshold, 'region': region}


def test_write_selected_masks(mask_manager, tmp_path):
    add_masks(mask_manager)

    with h5py.File(tmp_path / 'masks.h5', 'w') as f:
        # Exporting a selection must only write the selected masks
        mask_manager.write_masks(f.create_group('selected'), names=['region'])
        assert 'region' in f['selected']
        assert 'threshold' not in f['selected']

        # Without a selection (e.g. the state file) all of them are written
        mask_manager.write_masks(f.create_group('all'))
        assert {'region', 'threshold'} <= set(f['all'])


def test_invalidate_detector_masks_with_threshold(mask_manager):
    add_masks(mask_manager)
    region = mask_manager.masks['region']
    region.masked_arrays = 'stale'

    # This used to raise on the threshold mask's [min, max] data
    mask_manager.invalidate_detector_masks(['ge1'])
    assert region.masked_arrays is None
