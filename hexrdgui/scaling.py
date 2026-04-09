import functools
from typing import Any, Callable

import numpy as np

#####################
# Scaling Functions #
#####################


def none(x: np.ndarray) -> np.ndarray:
    return x


def sqrt(x: np.ndarray, global_min: float | None = None) -> np.ndarray:
    min_val = global_min if global_min is not None else np.nanmin(x)
    return np.sqrt(x - min_val)


def log(x: np.ndarray, global_min: float | None = None) -> np.ndarray:
    min_val = global_min if global_min is not None else np.nanmin(x)
    return np.log(x - min_val + 1)


def log_log_sqrt(x: np.ndarray, global_min: float | None = None) -> np.ndarray:
    min_val = global_min if global_min is not None else np.nanmin(x)
    return np.log(np.log(np.sqrt(x - min_val) + 1) + 1)


def _fill_masked(x: Any, fill_value: float = np.nan) -> np.ndarray:
    if isinstance(x, np.ma.masked_array):
        return x.filled(fill_value)
    return x


# This decorator automatically rescales the transform output to have
# the same range as the transform input.
def rescale_to_original(
    func: Callable[[np.ndarray], np.ndarray],
) -> Callable[[np.ndarray], np.ndarray]:
    def rescale_to_old(new: np.ndarray, old: Any) -> np.ndarray:
        new_range = (np.nanmin(new), np.nanmax(new))
        old_range = (np.nanmin(old), np.nanmax(old))
        return np.interp(new, new_range, old_range)

    @functools.wraps(func)
    def wrapper(old: np.ndarray) -> np.ndarray:
        new = func(_fill_masked(old))
        return rescale_to_old(new, old)

    return wrapper


SCALING_OPTIONS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    'none': none,
    'sqrt': sqrt,
    'log': log,
    'log-log-sqrt': log_log_sqrt,
}


# Apply rescaling to all except the none option
_rescaling_blacklist = ['none']
for k, v in SCALING_OPTIONS.items():
    if k in _rescaling_blacklist:
        continue

    SCALING_OPTIONS[k] = rescale_to_original(v)


def create_scaling_function(
    name: str,
    global_min: float | None = None,
) -> Callable[[np.ndarray], np.ndarray]:
    """Create a scaling function, optionally with a fixed global minimum.

    When global_min is provided, the scaling function uses that fixed
    value instead of computing np.nanmin(x) on each call. This prevents
    the image display from jumping when user masks happen to remove the
    current minimum pixel value.

    The rescale-to-original step also uses global_min as the stable
    lower bound, so that the output range doesn't shift when masked
    pixels change the apparent data range.

    When global_min is None, falls back to the default SCALING_OPTIONS
    behavior (computing the min on-the-fly).
    """
    if name == 'none' or global_min is None:
        return SCALING_OPTIONS[name]

    # Look up the unwrapped function by name. The module-level sqrt/log/
    # log_log_sqrt still accept global_min; only the SCALING_OPTIONS
    # entries got wrapped by rescale_to_original.
    base_func = {'sqrt': sqrt, 'log': log, 'log-log-sqrt': log_log_sqrt}[name]

    def wrapper(old: np.ndarray) -> np.ndarray:
        x = _fill_masked(old)
        new = base_func(x, global_min=global_min)

        # Rescale to the original data range, using stable bounds
        # for the lower end so masking doesn't shift the display.
        # All scaling functions produce 0 at x=global_min.
        new_range = (0.0, np.nanmax(new))
        old_range = (global_min, np.nanmax(old))
        return np.interp(new, new_range, old_range)

    return wrapper
