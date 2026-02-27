from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from hexrd.core.instrument import HEDMInstrument

# Type alias for the spots_data structure returned by fit_grains().
# Actual structure: {grain_id: (complvec, {det_key: [spot_list]})}
# Each spot is a list of 9 elements (see pull_spots trimmed output).
# Some callers convert to a list before passing (indexed by position),
# so we accept any int-indexable mapping or sequence.
_SpotsEntry: TypeAlias = 'tuple[list[np.bool_], dict[str, list]]'
SpotsData: TypeAlias = (
    'dict[int, _SpotsEntry] | list[_SpotsEntry] | Sequence[_SpotsEntry]'
)

# Per-detector, per-grain array dict used throughout this module.
DetGrainArrays: TypeAlias = 'dict[str, list[np.ndarray]]'

# The full return type of filter_spots_data (string-keyed for each field).
FilteredSpotsResult: TypeAlias = 'dict[str, dict[str, list[np.ndarray]]]'


def filter_spots_data(
    spots_data: SpotsData,
    instr: HEDMInstrument,
    grain_ids: NDArray[np.integer] | Sequence[int],
    ome_period: NDArray[np.floating] | None = None,
    refit_idx: dict[str, list[NDArray[np.bool_]]] | None = None,
) -> FilteredSpotsResult:
    """Filter raw spots data and extract all useful columns in one pass.

    This is the single entry point for parsing the per-grain, per-detector
    spot lists produced by ``pull_spots()`` (via ``fit_grains()``).

    Parameters
    ----------
    spots_data : dict
        ``{grain_id: (complvec, {det_key: [spot_list]})}``
    instr : HEDMInstrument
        Instrument with ``.detectors`` dict.
    grain_ids : array-like
        Grain IDs to process (order is preserved).
    ome_period : (2,) array, optional
        If given, measured omegas are remapped into this period.
    refit_idx : dict, optional
        ``{det_key: [bool_array_per_grain]}``.  When provided, these
        masks are used *instead* of the default valid-reflection /
        saturation filter.

    Returns
    -------
    dict with the following keys, each mapping to
    ``{det_key: [one_array_per_grain]}``:

    - ``'pred_angs'`` : Nx3 predicted [tth, eta, ome]  (from col 5)
    - ``'meas_angs'`` : Nx3 measured  [tth, eta, ome]  (from col 6)
    - ``'hkls'``      : Nx3 Miller indices              (from col 2)
    - ``'meas_xy'``   : Nx2 measured detector [x, y]   (from col 7)
    - ``'pred_xy'``   : Nx2 predicted detector [x, y]  (from col 8)
    - ``'idx'``       : boolean mask used for filtering
    """
    from hexrd.rotations import mapAngle

    result_keys = ('pred_angs', 'meas_angs', 'hkls', 'meas_xy', 'pred_xy', 'idx')
    out: FilteredSpotsResult = {k: {} for k in result_keys}

    for det_key, panel in instr.detectors.items():
        for k in result_keys:
            out[k][det_key] = []

        for ig, grain_id in enumerate(grain_ids):
            raw = spots_data[grain_id][1][det_key]
            data: np.ndarray = np.array(raw, dtype=object)

            if data.size == 0:
                out['pred_angs'][det_key].append(np.empty((0, 3)))
                out['meas_angs'][det_key].append(np.empty((0, 3)))
                out['hkls'][det_key].append(np.empty((0, 3)))
                out['meas_xy'][det_key].append(np.empty((0, 2)))
                out['pred_xy'][det_key].append(np.empty((0, 2)))
                out['idx'][det_key].append(np.empty((0,), dtype=bool))
                continue

            # Determine the filter mask
            if refit_idx is None:
                valid_reflections = data[:, 0] >= 0
                not_saturated = data[:, 4] < panel.saturation_level
                idx = np.logical_and(valid_reflections, not_saturated)
            else:
                idx = refit_idx[det_key][ig]

            out['idx'][det_key].append(idx)

            if not np.any(idx):
                out['pred_angs'][det_key].append(np.empty((0, 3)))
                out['meas_angs'][det_key].append(np.empty((0, 3)))
                out['hkls'][det_key].append(np.empty((0, 3)))
                out['meas_xy'][det_key].append(np.empty((0, 2)))
                out['pred_xy'][det_key].append(np.empty((0, 2)))
                continue

            out['pred_angs'][det_key].append(np.vstack(data[idx, 5]))
            out['meas_angs'][det_key].append(np.vstack(data[idx, 6]))
            out['hkls'][det_key].append(np.vstack(data[idx, 2]))
            out['meas_xy'][det_key].append(np.vstack(data[idx, 7]))
            out['pred_xy'][det_key].append(np.vstack(data[idx, 8]))

            # Remap omegas if requested
            if ome_period is not None:
                meas_angs = out['meas_angs'][det_key][-1]
                meas_angs[:, 2] = mapAngle(meas_angs[:, 2], ome_period)

    return out


def extract_spot_angles(
    spots_data: SpotsData,
    instr: HEDMInstrument,
    grain_ids: NDArray[np.integer] | Sequence[int],
) -> tuple[DetGrainArrays, DetGrainArrays]:
    """Extract predicted and measured angles from raw spots data.

    Returns
    -------
    pred_angs : {det_key: [Nx3 array per grain]}
        Predicted [tth, eta, ome].
    meas_angs : {det_key: [Nx3 array per grain]}
        Measured [tth, eta, ome].
    """
    out = filter_spots_data(spots_data, instr, grain_ids)
    return out['pred_angs'], out['meas_angs']


def extract_spot_xyo(
    spots_data: SpotsData,
    instr: HEDMInstrument,
    grain_ids: NDArray[np.integer] | Sequence[int],
) -> tuple[DetGrainArrays, DetGrainArrays]:
    """Extract predicted and measured XY+omega from raw spots data.

    Returns
    -------
    xyo_pred : {det_key: [Nx3 array per grain]}
        Predicted [x, y, ome].
    xyo_det : {det_key: [Nx3 array per grain]}
        Measured [x, y, ome].
    """
    out = filter_spots_data(spots_data, instr, grain_ids)
    xyo_pred: DetGrainArrays = {}
    xyo_det: DetGrainArrays = {}

    for det_key in out['pred_xy']:
        xyo_pred[det_key] = []
        xyo_det[det_key] = []
        for i in range(len(out['pred_xy'][det_key])):
            pred_xy: np.ndarray = out['pred_xy'][det_key][i]
            meas_xy: np.ndarray = out['meas_xy'][det_key][i]
            pred_angs: np.ndarray = out['pred_angs'][det_key][i]
            meas_angs: np.ndarray = out['meas_angs'][det_key][i]

            if pred_xy.shape[0] == 0:
                xyo_pred[det_key].append(np.empty((0, 3)))
                xyo_det[det_key].append(np.empty((0, 3)))
            else:
                xyo_pred[det_key].append(np.column_stack([pred_xy, pred_angs[:, 2]]))
                xyo_det[det_key].append(np.column_stack([meas_xy, meas_angs[:, 2]]))

    return xyo_pred, xyo_det


def parse_spots_data(
    spots_data: SpotsData,
    instr: HEDMInstrument,
    grain_ids: NDArray[np.integer] | Sequence[int],
    ome_period: NDArray[np.floating] | None = None,
    refit_idx: dict[str, list[NDArray[np.bool_]]] | None = None,
) -> tuple[DetGrainArrays, DetGrainArrays, dict[str, list[np.ndarray]]]:
    """Parse spots data for calibration, returning hkls, xyo_det, and idx.

    This is the original interface used by the HEDM calibration workflow.

    Returns
    -------
    hkls : {det_key: [Nx3 array per grain]}
    xyo_det : {det_key: [Nx3 array per grain]}
        Measured [x, y, ome].
    idx : {det_key: [bool_array per grain]}
    """
    out = filter_spots_data(
        spots_data,
        instr,
        grain_ids,
        ome_period=ome_period,
        refit_idx=refit_idx,
    )

    # Build xyo_det: [meas_xy, meas_ome] combined into Nx3
    xyo_det: DetGrainArrays = {}
    for det_key in out['meas_xy']:
        xyo_det[det_key] = []
        for i in range(len(out['meas_xy'][det_key])):
            meas_xy: np.ndarray = out['meas_xy'][det_key][i]
            meas_angs: np.ndarray = out['meas_angs'][det_key][i]
            if meas_xy.shape[0] == 0:
                xyo_det[det_key].append(np.empty((0, 3)))
            else:
                meas_omes = meas_angs[:, 2].reshape(-1, 1)
                xyo_det[det_key].append(np.hstack([meas_xy, meas_omes]))

    return out['hkls'], xyo_det, out['idx']
