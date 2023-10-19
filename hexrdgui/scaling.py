import functools

import numpy as np

#####################
# Scaling Functions #
#####################


def none(x):
    return x


def sqrt(x):
    return np.sqrt(x - np.nanmin(x))


def log(x):
    return np.log(x - np.nanmin(x) + 1)


def log_log_sqrt(x):
    return np.log(np.log(np.sqrt(x - np.nanmin(x)) + 1) + 1)


# This decorator automatically rescales the transform output to have
# the same range as the transform input.
def rescale_to_original(func):
    def rescale_to_old(new, old):
        new_range = (np.nanmin(new), np.nanmax(new))
        old_range = (np.nanmin(old), np.nanmax(old))
        return np.interp(new, new_range, old_range)

    @functools.wraps(func)
    def wrapper(old):
        new = func(old)
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
