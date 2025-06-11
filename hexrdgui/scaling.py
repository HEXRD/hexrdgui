import functools

import numpy as np

#####################
# Scaling Functions #
#####################


def none(x: np.ndarray) -> np.ndarray:
    return x


def sqrt(x: np.ndarray) -> np.ndarray:
    y = np.sqrt(x + 1)
    return y - np.nanmin(y)


def log(x: np.ndarray) -> np.ndarray:
    y = np.log(x + 1)
    return y - np.nanmin(y)


def log_log_sqrt(x: np.ndarray) -> np.ndarray:
    y = np.log(np.log(np.sqrt(x + 1) + 1) + 1)
    return y - np.nanmin(y)

# This decorator automatically rescales the transform output to have
# the same range as the transform input.
def rescale_to_original(func):
    def rescale_to_old(new, old):
        new_range = (np.nanmin(new), np.nanmax(new))
        old_range = (np.nanmin(old), np.nanmax(old))
        return np.interp(new, new_range, old_range)

    def fill_masked(x, fill_value=np.nan):
        if isinstance(x, np.ma.masked_array):
            return x.filled(fill_value)
        return x

    @functools.wraps(func)
    def wrapper(old):
        new = func(fill_masked(old))
        return rescale_to_old(new, old)

    return wrapper


SCALING_OPTIONS = {
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
