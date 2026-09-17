"""Gap #1: the dark frame can be read from its own HDF5 dataset path.

ImageFileManager.open_file gained an optional `path` kwarg that overrides
self.path for a single call (without mutating it), so the dark frames can live
at a different dataset path than the data (e.g. /exchange/dark vs
/exchange/data), including in the same HDF5 file (the APS/Varex layout).
"""
import h5py
import numpy as np
import pytest

from hexrdgui.image_file_manager import ImageFileManager


@pytest.fixture
def aps_like_file(tmp_path):
    # Mirrors Andrew Chuang's layout: data + dark in one file, frames on axis 0.
    f = tmp_path / 'aps_like.h5'
    rng = np.random.default_rng(0)
    data = (rng.random((5, 16, 16)) * 100 + 50).astype(np.uint16)
    dark = (rng.random((3, 16, 16)) * 100 + 900).astype(np.uint16)  # higher mean
    with h5py.File(f, 'w') as h5:
        g = h5.create_group('exchange')
        g.create_dataset('data', data=data)
        g.create_dataset('dark', data=dark)
    return str(f), data, dark


def test_data_read_uses_self_path(qtbot, aps_like_file):
    f, data, _ = aps_like_file
    ifm = ImageFileManager()
    ifm.path = ['exchange', 'data']
    ims = ifm.open_file(f)
    assert len(ims) == 5
    assert ims.shape == (16, 16)
    np.testing.assert_array_equal(ims[0], data[0])


def test_dark_read_from_other_dataset_same_file(qtbot, aps_like_file):
    f, _, dark = aps_like_file
    ifm = ImageFileManager()
    ifm.path = ['exchange', 'data']
    # The point of gap #1: read dark from a DIFFERENT dataset in the SAME file.
    dims = ifm.open_file(f, path=['exchange', 'dark'])
    assert len(dims) == 3
    np.testing.assert_array_equal(dims[0], dark[0])


def test_self_path_not_mutated_by_dark_read(qtbot, aps_like_file):
    f, data, _ = aps_like_file
    ifm = ImageFileManager()
    ifm.path = ['exchange', 'data']
    ifm.open_file(f, path=['exchange', 'dark'])
    # self.path must be preserved so later data reads stay correct
    assert ifm.path == ['exchange', 'data']
    again = ifm.open_file(f)
    np.testing.assert_array_equal(again[0], data[0])


def test_dark_has_higher_mean_than_data(qtbot, aps_like_file):
    f, _, _ = aps_like_file
    ifm = ImageFileManager()
    ifm.path = ['exchange', 'data']
    data = ifm.open_file(f)
    dark = ifm.open_file(f, path=['exchange', 'dark'])
    assert np.asarray(dark[0], float).mean() > np.asarray(data[0], float).mean()
