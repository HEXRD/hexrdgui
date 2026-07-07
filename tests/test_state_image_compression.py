"""Tests for blosc-zstd compression of dense image data in state files.

Data that is not eligible for the sparse fch5 format (signed dtypes, dense
frames) keeps the 'hdf5' imageseries layout with a blosc-zstd filter, so it
round-trips through ``imageseries.open(..., 'hdf5', ...)`` and stays backward
compatible.
"""

from pathlib import Path

import h5py
import numpy as np

from hexrd.core import imageseries

from hexrdgui.state import write_imageseries


def make_imageseries() -> tuple:
    # A small, sparse imageseries with omega metadata. The signed dtype (with
    # negative values) keeps it on the dense hdf5 path.
    data = np.zeros((5, 64, 64), dtype=np.int16)
    data[:, ::8, ::8] = 1000
    data[:, 3, 3] = -5
    ims = imageseries.open(None, 'array', data=data)
    ims.metadata['omega'] = np.linspace(0, 180, 5).reshape(-1, 1)
    return ims, data


def test_roundtrip_lossless(tmp_path: Path) -> None:
    ims, data = make_imageseries()
    path = tmp_path / 'state.h5'
    with h5py.File(path, 'w') as f:
        write_imageseries(f, 'images/det', ims)

    with h5py.File(path, 'r') as f:
        loaded = imageseries.open(
            f, 'hdf5', path='images/det', close_when_finished=False
        )
        for i in range(len(data)):
            assert np.array_equal(np.asarray(loaded[i]), data[i])
        assert np.allclose(loaded.metadata['omega'], ims.metadata['omega'])


def test_images_are_compressed(tmp_path: Path) -> None:
    ims, data = make_imageseries()
    path = tmp_path / 'state.h5'
    with h5py.File(path, 'w') as f:
        write_imageseries(f, 'images/det', ims)

    with h5py.File(path, 'r') as f:
        dataset = f['images/det/images']
        # Sparse data compresses dramatically, and the blosc filter (id 32001)
        # is applied rather than the old gzip default.
        assert dataset.id.get_storage_size() < data.nbytes // 2
        assert '32001' in dataset._filters
