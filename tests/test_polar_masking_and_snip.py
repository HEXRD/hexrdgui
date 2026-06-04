"""
Polar-view masking integration test.

Exercises the polar view end-to-end with the various mask types, locking in
the "apply threshold mask before warping" behavior (HEXRD/hexrdgui#1689):

  1. Launch the GUI, load the GE_WPPF (Ceria powder) state file, switch to
     the polar view, and compare the (unmasked) polar image against a
     committed golden array (nan-aware, with tolerance).
  2. Add a *visible* hand-drawn polygon mask and a *border-only* hand-drawn
     rectangle mask and verify they modify the polar view as expected
     (visible masks remove pixels from the displayed image; border-only
     masks only affect the computational image).
  3. Add a threshold mask and verify it actually removes data from the polar
     view, only ever masking (never un-masking or altering surviving pixels).
     Because the threshold is applied to the raw detector image *before*
     warping, a normal re-warp is all that is needed.
  4. With every mask applied, turn SNIP on for two algorithms and verify the
     polar view still renders correctly.  This specifically covers a SNIP
     algorithm that *can* ingest NaNs (SNIP_2D) and one that *cannot*
     (Fast_SNIP_1D): the pre-warp threshold introduces NaNs, and the no-NaN
     algorithm must still produce a sane image (no NaN-poisoned rows).

Determinism notes:
  * Intensity corrections are disabled -- they settle on a deferred signal
    and would otherwise make the polar values non-deterministic.
  * SNIP erosion is disabled -- it is an independent masking step that would
    otherwise confound the "did SNIP preserve the masked pattern" check.
  * The polar resolution is pinned -- the GUI otherwise auto-derives it from
    the instrument on a deferred signal.
  * SNIP_1D is intentionally not exercised: its background estimator uses a
    ProcessPoolExecutor that does not survive the forked Qt test process.
    SNIP_2D is the NaN-capable representative instead.

Run with:
    cd hexrdgui/tests && QT_QPA_PLATFORM=offscreen \\
        python -m pytest test_polar_threshold_mask.py -v -s
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from hexrdgui.calibration.polar_plot import polar_viewer
from hexrdgui.constants import ViewType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.constants import MaskType
from hexrdgui.masking.mask_manager import MaskManager
from hexrdgui.utils import SnipAlgorithmType, add_sample_points

DATA_DIR = Path(__file__).resolve().parent / 'data'
GOLDEN_POLAR = DATA_DIR / 'polar_baseline_ge_wppf.npz'

# The GE_WPPF instrument has a single detector named "ge3".
DET = 'ge3'

# Threshold band on the *raw* detector counts (median ~78, max ~12305).
# Chosen to mask a large, unambiguous fraction of the polar view (~59%)
# while leaving plenty of pixels for SNIP to operate on.
THRESHOLD_DATA = [80.0, 1000.0]

# Deterministic polar resolution + non-confounding processing flags.
# (apply_snip1d / snip1d_algorithm are set per-step by the test.)
POLAR_CONFIG = {
    'pixel_size_tth': 0.05,
    'pixel_size_eta': 1.0,
    'tth_min': 2.0,
    'tth_max': 14.0,
    'eta_min': 0.0,
    'eta_max': 360.0,
    'apply_erosion': False,
}


@pytest.fixture
def ge_wppf_state(example_repo_path):
    state_file = example_repo_path / 'state_examples' / 'GE_WPPF' / 'ge_wppf.h5'
    assert state_file.exists(), f'Missing test file: {state_file}'
    return state_file


def _rect_polygon(x0: float, y0: float, w: float, h: float) -> np.ndarray:
    """A closed rectangle in raw detector pixel coordinates.

    Sampled densely so the raw->polar conversion of the perimeter stays
    accurate (matching what the hand-drawn mask tooling does).
    """
    verts = np.array(
        [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h], [x0, y0]],
        dtype=float,
    )
    return add_sample_points(verts, 400)


def _clear_masks() -> None:
    mgr = MaskManager()
    for name in list(mgr.masks):
        mgr.remove_mask(name)


def _pin_polar_config() -> None:
    """Pin the deterministic polar resolution / processing flags.

    Set the config dict directly (no setters) so we do not kick off the
    deferred auto-resolution that would otherwise race with generation.
    """
    HexrdConfig().config['image']['polar'].update(POLAR_CONFIG)


def _generate_polar() -> np.ndarray:
    """Generate the polar view's displayed image via the GUI worker entry.

    ``polar_viewer()`` is exactly what the image canvas runs in its
    background thread; calling it directly keeps the test deterministic.
    """
    _pin_polar_config()
    return np.array(polar_viewer().display_img)


def _assert_masking_only(
    masked: np.ndarray,
    reference: np.ndarray,
    *,
    atol: float = 1e-4,
) -> None:
    """Assert ``masked`` is ``reference`` with strictly more pixels removed.

    A correct mask only ever turns finite pixels into NaN -- it never
    revives a masked pixel and never alters a surviving pixel's value.
    """
    masked_finite = np.isfinite(masked)
    ref_finite = np.isfinite(reference)

    # Surviving pixels must be a subset of the previously-finite pixels.
    assert np.all(masked_finite <= ref_finite), (
        'Masking revealed pixels that were previously masked'
    )
    # Something must actually have been removed.
    assert masked_finite.sum() < ref_finite.sum(), 'Mask did not remove any pixels'
    # Surviving pixel values are untouched by the mask.
    np.testing.assert_allclose(
        masked[masked_finite],
        reference[masked_finite],
        atol=atol,
        err_msg='Masking altered the value of a surviving pixel',
    )


def _load_dataset(main_window, ge_wppf_state) -> None:
    main_window.load_state_file(ge_wppf_state)
    QApplication.processEvents()

    assert HexrdConfig().detector_names == [DET]

    # Intensity corrections settle asynchronously; disable them so the polar
    # values are deterministic (this test is about masking, not corrections).
    HexrdConfig().disable_all_intensity_corrections()
    QApplication.processEvents()


def _switch_to_polar(main_window) -> None:
    """Switch the running GUI to the polar view."""
    main_window.image_mode_widget.set_image_mode_widget_tab(ViewType.polar)
    QApplication.processEvents()
    assert HexrdConfig().image_mode == ViewType.polar


def test_polar_view_masks(qtbot, main_window, ge_wppf_state):
    _clear_masks()
    HexrdConfig().config['image']['polar']['apply_snip1d'] = False

    # ── Step 1: load data and switch the GUI to the polar view ─────────
    _load_dataset(main_window, ge_wppf_state)
    _switch_to_polar(main_window)

    mgr = MaskManager()
    mgr.view_mode = ViewType.polar

    baseline = _generate_polar()

    # ── Step 2: verify the polar view matches the golden array ─────────
    golden = np.load(GOLDEN_POLAR)['display_img'].astype(float)
    assert baseline.shape == golden.shape, (
        f'Polar shape {baseline.shape} != golden {golden.shape}'
    )
    # NaN (masked / off-detector) pixels must line up exactly...
    np.testing.assert_array_equal(
        np.isfinite(baseline),
        np.isfinite(golden),
        err_msg='Polar view NaN pattern differs from golden',
    )
    # ...and the finite intensities must match within tolerance.
    finite = np.isfinite(golden)
    np.testing.assert_allclose(
        baseline[finite],
        golden[finite],
        atol=1e-2,
        err_msg='Polar view intensities differ from golden beyond tolerance',
    )

    # ── Step 3: hand-drawn masks (visible polygon + border-only rect) ──
    # Visible polygon: removes its interior from the *displayed* image.
    polygon = mgr.add_mask(
        data=[(DET, _rect_polygon(700, 700, 400, 400))],
        mtype=MaskType.polygon,
        name='polygon_visible',
        visible=True,
    )
    assert polygon.visible and not polygon.show_border

    # Border-only rectangle: visible=False, show_border=True.  It must NOT
    # change the displayed image, but it *does* apply to the computational
    # image.
    rectangle = mgr.add_mask(
        data=[(DET, _rect_polygon(1300, 1300, 250, 250))],
        mtype=MaskType.region,
        name='rectangle_border',
        visible=False,
    )
    rectangle.show_border = True
    assert not rectangle.visible and rectangle.show_border

    # Re-warp with the hand-drawn masks present.
    iviewer = polar_viewer()
    masks_display = np.array(iviewer.display_img)
    masks_comp = np.array(iviewer.img)

    # The visible polygon removed pixels from the displayed image, only ever
    # masking (subset of baseline, surviving values unchanged).
    _assert_masking_only(masks_display, baseline)

    # The border-only rectangle does not touch the displayed image but does
    # remove additional pixels from the computational image.
    comp_finite = np.isfinite(masks_comp)
    disp_finite = np.isfinite(masks_display)
    assert np.all(comp_finite <= disp_finite), (
        'Computational image has finite pixels the display image lacks'
    )
    assert comp_finite.sum() < disp_finite.sum(), (
        'Border-only rectangle did not affect the computational image'
    )

    # ── Step 4: threshold mask applied *before* warping ────────────────
    threshold = mgr.add_mask(
        data=list(THRESHOLD_DATA),
        mtype=MaskType.threshold,
        name='threshold',
        visible=True,
    )
    assert mgr.threshold_mask is threshold
    assert threshold.data == THRESHOLD_DATA

    # A normal re-warp applies the threshold (it is folded into the warp,
    # so there is no dependency on the already-computed polar image).
    thresholded = _generate_polar()

    # The threshold actually modified the data, only ever masking.
    #
    # The surviving-value tolerance is 1 count here (not ~0): applying the
    # threshold requires casting the raw uint16 image to float before warping
    # (to carry NaNs), and `_interpolate_bilinear` produces results that
    # differ by up to 1 count between integer and float inputs.  That bounded
    # precision difference is expected -- the threshold still only ever masks
    # pixels, it does not meaningfully alter the surviving intensities.
    _assert_masking_only(thresholded, masks_display, atol=1.0 + 1e-6)
    # It is applied to the *raw* counts, so it removes a large fraction of
    # the view (this band masks ~half on the raw image; it would barely do
    # anything if it were -- incorrectly -- applied to the processed polar
    # image).
    removed_fraction = 1 - np.isfinite(thresholded).sum() / disp_finite.sum()
    assert removed_fraction > 0.4, (
        f'Threshold removed only {removed_fraction:.1%} -- expected the raw '
        f'threshold to mask a large fraction of the view'
    )

    # Hiding the threshold restores the hand-drawn-masks-only view exactly.
    threshold.visible = False
    restored = _generate_polar()
    np.testing.assert_array_equal(
        np.isfinite(restored),
        disp_finite,
        err_msg='Hiding the threshold did not restore the unthresholded view',
    )
    threshold.visible = True

    # The masked (no-SNIP) NaN pattern that SNIP must preserve.
    thresholded_finite = np.isfinite(thresholded)

    # ── Step 5: turn SNIP on for each algorithm, with all masks applied ─
    # The pre-warp threshold injects NaNs.  Verify both a NaN-capable
    # algorithm (SNIP_2D) and the no-NaN Fast_SNIP_1D produce a sane polar
    # view: no infinities, the exact same NaN pattern as without SNIP (i.e.
    # no NaN-poisoned rows), and actually-changed (background-subtracted)
    # intensities.
    polar_config = HexrdConfig().config['image']['polar']
    polar_config['apply_snip1d'] = True
    try:
        for algorithm in (
            SnipAlgorithmType.Fast_SNIP_1D,  # cannot ingest NaNs
            SnipAlgorithmType.SNIP_2D,  # NaN-capable
        ):
            polar_config['snip1d_algorithm'] = int(algorithm)
            snipped = _generate_polar()
            label = algorithm.name

            assert not np.isinf(snipped).any(), (
                f'{label}: SNIP polar view has infinities'
            )
            # SNIP changes only values, never the mask: the NaN pattern must
            # exactly match the no-SNIP thresholded view.  A no-NaN algorithm
            # that choked on the threshold NaNs would poison whole rows and
            # fail here.
            np.testing.assert_array_equal(
                np.isfinite(snipped),
                thresholded_finite,
                err_msg=f'{label}: SNIP changed the masked (NaN) pattern',
            )
            # SNIP is a background subtraction -- surviving values must move.
            both_finite = thresholded_finite
            assert not np.allclose(snipped[both_finite], thresholded[both_finite]), (
                f'{label}: SNIP did not change any pixel values'
            )
    finally:
        polar_config['apply_snip1d'] = False

    _clear_masks()
