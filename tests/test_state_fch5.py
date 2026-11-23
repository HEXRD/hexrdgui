"""Tests for storing state-file imageseries as fch5 frame caches."""

from pathlib import Path

import h5py
import numpy as np

from hexrd.core import imageseries

from hexrdgui.state import open_imageseries, write_imageseries


def make_imageseries(data: np.ndarray):
    ims = imageseries.open(None, 'array', data=data)
    ims.metadata['omega'] = np.linspace(0, 180, len(data)).reshape(-1, 1)
    return ims


def roundtrip(tmp_path: Path, data: np.ndarray) -> bool:
    """Write, reopen, and verify an imageseries; return whether fch5 was used."""
    ims = make_imageseries(data)
    path = tmp_path / 'state.h5'
    with h5py.File(path, 'w') as f:
        write_imageseries(f, 'images/det', ims)

    with h5py.File(path, 'r') as f:
        loaded = open_imageseries(f, 'images/det')
        assert loaded.dtype == data.dtype
        for i in range(len(data)):
            assert np.array_equal(np.asarray(loaded[i]), data[i])
        assert np.allclose(loaded.metadata['omega'], ims.metadata['omega'])
        group = f['images/det']
        if 'HEXRD_FRAMECACHE_VERSION' in group.attrs:
            # Sparse storage: only the nonzero values are stored
            assert group['data'].shape[0] == np.count_nonzero(data)
            return True

        return False


def test_sparse_unsigned_written_as_fch5(tmp_path: Path) -> None:
    data = np.zeros((5, 64, 64), dtype=np.uint16)
    data[:, ::8, ::8] = 1000
    assert roundtrip(tmp_path, data)


def test_ineligible_data_falls_back_to_dense(tmp_path: Path) -> None:
    # Signed data: fch5 with threshold=0 would zero out negative values
    data = np.zeros((5, 64, 64), dtype=np.int32)
    data[:, ::8, ::8] = 1000
    data[:, 3, 3] = -7
    assert not roundtrip(tmp_path, data)

    # Unsigned but not sparse: dense storage compresses better
    data = np.arange(5 * 64 * 64, dtype=np.uint32).reshape(5, 64, 64) + 1
    assert not roundtrip(tmp_path, data)


def test_old_state_layout_still_loads(tmp_path: Path) -> None:
    # Old state files always used the dense hdf5 layout with the gzip default
    data = np.zeros((5, 64, 64), dtype=np.uint16)
    data[:, ::8, ::8] = 1000
    ims = make_imageseries(data)
    path = tmp_path / 'state.h5'
    with h5py.File(path, 'w') as f:
        imageseries.write(ims, f, 'hdf5', path='images/det')

    with h5py.File(path, 'r') as f:
        loaded = open_imageseries(f, 'images/det')
        for i in range(len(data)):
            assert np.array_equal(np.asarray(loaded[i]), data[i])
        assert np.allclose(loaded.metadata['omega'], ims.metadata['omega'])
