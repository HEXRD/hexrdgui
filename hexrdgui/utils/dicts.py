import numpy as np


def ensure_all_keys_match(dict1: dict, dict2: dict) -> dict:
    # This ensures that all keys in dict1 match the keys in dict2.
    # If they do not match, a KeyError will be raised.
    # A dict is returned where the keys in dict2 are sorted to match
    # those in dict1.

    def recurse(this: dict, other: dict, ret: dict, path: list) -> None:
        this_keys = sorted(this.keys())
        other_keys = sorted(other.keys())
        if this_keys != other_keys:
            this_keys_str = ', '.join(f'"{x}"' for x in this_keys)
            other_keys_str = ', '.join(f'"{x}"' for x in other_keys)
            msg = f'keys1 {this_keys_str} failed to match keys2 {other_keys_str}'
            if path:
                path_str = ' -> '.join(path)
                msg += f' for path "{path_str}"'
            raise KeyError(msg)

        for k, v in this.items():
            if isinstance(v, dict):
                ret[k] = {}
                recurse(v, other[k], ret[k], path + [k])
            else:
                ret[k] = other[k]

    ret: dict = {}
    recurse(dict1, dict2, ret, [])
    return ret


def ndarrays_to_lists(d: dict) -> None:
    # Convert all numpy arrays in a dict into lists
    for k, v in d.items():
        if isinstance(v, dict):
            ndarrays_to_lists(v)
        elif isinstance(v, np.ndarray):
            d[k] = v.tolist()
