"""Gap #2: import a static invalid-pixel mask file as a panel buffer.

PanelBufferDialog loads a mask file and (when the "File marks excluded pixels"
checkbox is set) inverts it into the panel-buffer convention (True = valid).
These tests cover the new file loader, _load_mask_file, which reads both NumPy
(.npy) and fabio-readable images (.tif), plus the invert convention.
"""
import numpy as np
import pytest

from hexrdgui.calibration.panel_buffer_dialog import PanelBufferDialog

SHAPE = (16, 16)


def _mask():
    m = np.zeros(SHAPE, dtype=bool)
    m[:, 3] = True
    return m


def test_load_mask_file_npy(qtbot, tmp_path):
    m = _mask()
    p = tmp_path / 'mask.npy'
    np.save(p, m)
    out = PanelBufferDialog._load_mask_file(None, str(p))
    assert out.shape == SHAPE
    np.testing.assert_array_equal(out.astype(bool), m)


def test_load_mask_file_tiff(qtbot, tmp_path):
    fabio = pytest.importorskip('fabio')
    m = _mask()
    p = tmp_path / 'mask.tif'
    fabio.tifimage.TifImage(data=(m * 255).astype(np.uint16)).write(str(p))
    out = PanelBufferDialog._load_mask_file(None, str(p))
    assert out.shape == SHAPE
    np.testing.assert_array_equal(out.astype(bool), m)


def test_load_then_invert_to_valid_pixels(qtbot, tmp_path):
    # End-to-end of the gap #2 pieces: load a file, then apply the dialog's
    # invert (file marks excluded pixels) -> valid-pixel panel buffer.
    m = _mask()
    p = tmp_path / 'mask.npy'
    np.save(p, m)
    arr = PanelBufferDialog._load_mask_file(None, str(p))
    # This mirrors what current_editing_buffer_value does when the
    # "File marks excluded (masked) pixels" checkbox is checked.
    buf = ~arr.astype(bool)
    # Excluded pixels in the buffer == masked pixels in the file
    assert int((~buf).sum()) == int(m.sum())
    assert not buf[0, 3]   # masked -> excluded
    assert buf[0, 0]       # unmasked -> valid
