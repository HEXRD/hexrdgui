from pathlib import Path

import h5py

from hexrdgui.hexrd_config import HexrdConfig


def update_if_needed(file_path: str | Path) -> None:
    # Find and fix any issues with the state file
    fix_issue_1227(file_path)


def has_issue_1227(file_path: str | Path) -> bool:
    # Issue 1227 is where `\` was used on Windows for paths inside the HDF5
    # file instead of `/`
    with h5py.File(file_path, 'r') as rf:
        return any(x.startswith('config\\') for x in rf.keys())


def fix_issue_1227(file_path: str | Path) -> None:
    if not has_issue_1227(file_path):
        return

    logger = HexrdConfig().logger
    logger.warning('State file found to contain issue #1227. Fixing it up...')

    from hexrdgui.state import _load_config, _save_config

    with h5py.File(file_path, 'a') as f:

        # First, convert the yaml config and load it.
        # It is currently using paths with '\' internally.
        key = 'config\\yaml'
        new_path = '/'.join(key.split('\\'))
        f[new_path] = f[key]
        del f[key]

        # Load the config while it is still using '\' paths
        config = _load_config(f)
        del f[new_path]

        # Remove any other keys that contain '\\'
        for key in list(f.keys()):
            if key.startswith('config\\'):
                del f[key]

        # Now, save the config back in with updated paths
        _save_config(f, config)
