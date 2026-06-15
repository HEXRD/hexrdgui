"""Regression tests for distortion-aware polar view caching.

`project_on_detector` is memoized and a distortion object is hashed by
identity, but calibration mutates its params in place. So the cache must key on
the distortion name/params (injected by `args_project_on_detector`), or it
returns a stale warp after a refine.
"""

from types import SimpleNamespace
from typing import Any

import numpy as np

from hexrd.core.distortion import get_mapping
from hexrd.core.distortion.distortionabc import DistortionABC

from hexrdgui.calibration.polarview import PolarView, project_on_detector


# GE_41RT forward/inverse takes 6 params.
GE_PARAMS = [-5.24e-7, -7.15e-5, -5.19e-4, 2, 4, 2]


def make_args(
    distortion: DistortionABC | None,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    # `args_project_on_detector` only reads `self.chi`/`self.tvec_s`, so a
    # lightweight stand-in avoids building a full instrument.
    fake_self = SimpleNamespace(chi=0.0, tvec_s=np.zeros(3))
    detector = SimpleNamespace(
        bvec=np.array([0.0, 0.0, -1.0]),
        rmat=np.eye(3),
        tvec=np.zeros(3),
        distortion=distortion,
    )
    # The stand-ins only need to quack like a PolarView/Detector here.
    return PolarView.args_project_on_detector(
        fake_self,  # type: ignore[arg-type]
        detector,  # type: ignore[arg-type]
    )


def stub_projection(
    gvec_angs: np.ndarray, *args: Any, **kwargs: Any
) -> tuple[np.ndarray, None, np.ndarray]:
    # Return a value derived from the current distortion params so a stale
    # cache hit is detectable. Duck-type to stay robust to arg-order changes;
    # use a sentinel when distortion is off.
    distortion = next(
        (a for a in args if hasattr(a, 'params') and hasattr(a, 'maptype')),
        None,
    )
    value = -1.0 if distortion is None else float(distortion.params[0])
    n = len(gvec_angs)
    xys = np.full((n, 2), value)
    valid_mask = np.ones(n, dtype=bool)
    return xys, None, valid_mask


def project(distortion: DistortionABC | None) -> np.ndarray:
    args, kwargs = make_args(distortion)
    grid = (np.array([[0.5]]), np.array([[0.5]]))
    return project_on_detector(grid, 1, 1, stub_projection, *args, **kwargs)


def test_args_include_distortion_in_cache_key() -> None:
    distortion = get_mapping('GE_41RT', GE_PARAMS)
    _, kwargs = make_args(distortion)

    assert kwargs['_distortion_func_name'] == 'GE_41RT'
    assert np.array_equal(kwargs['_distortion_params'], distortion.params)


def test_no_distortion_uses_none_in_cache_key() -> None:
    _, kwargs = make_args(None)

    assert kwargs['_distortion_func_name'] is None
    assert kwargs['_distortion_params'] is None


def test_cache_invalidated_on_in_place_param_change() -> None:
    # The calibration scenario: params mutated in place. Without the fix, the
    # second call returns the stale warp.
    distortion = get_mapping('GE_41RT', GE_PARAMS)

    before = project(distortion)

    distortion.params = [9.9, 0.0, 0.0, 2, 4, 2]
    after = project(distortion)

    assert not np.array_equal(before, after)


def test_cache_invalidated_on_distortion_toggle() -> None:
    # Toggling off should not reuse the with-distortion warp.
    distortion = get_mapping('GE_41RT', [1.0, 0.0, 0.0, 2, 4, 2])

    with_distortion = project(distortion)
    without_distortion = project(None)

    assert not np.array_equal(with_distortion, without_distortion)
