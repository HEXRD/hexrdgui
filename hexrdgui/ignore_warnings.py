"""Suppress known harmless warnings. Call apply() early in main.py."""

import os
import warnings


def apply():
    # Suppress harmless leaked semaphore warning from loky at shutdown.
    # The resource_tracker runs as a separate daemon process, so
    # warnings.filterwarnings only covers the main process. We also
    # set PYTHONWARNINGS so the filter propagates to the tracker.
    warnings.filterwarnings(
        'ignore',
        message=r'resource_tracker:.*leaked semaphore',
        category=UserWarning,
    )
    # Panels cover only part of the polar and stereo views, so regions
    # with no detector behind them are entirely NaN.  Reductions over
    # those regions are expected and their result is used as-is.
    warnings.filterwarnings(
        'ignore',
        message=r'All-NaN (slice|axis) encountered',
        category=RuntimeWarning,
    )

    _pw = os.environ.get('PYTHONWARNINGS', '')
    _filter = 'ignore:resource_tracker:UserWarning'
    if _filter not in _pw:
        os.environ['PYTHONWARNINGS'] = f'{_pw},{_filter}' if _pw else _filter
