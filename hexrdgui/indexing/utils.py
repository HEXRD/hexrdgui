from typing import Any

import numpy as np

from hexrd import constants
from hexrd import instrument
from hexrd.transforms import xfcapi


def generate_grains_table(qbar: np.ndarray) -> np.ndarray:
    num_grains = qbar.shape[1]
    grains_table = np.empty((num_grains, 21))
    gw = instrument.GrainDataWriter(array=grains_table)
    for i, q in enumerate(qbar.T):
        phi = 2 * np.arccos(q[0])
        n = xfcapi.unitRowVector(q[1:])
        grain_params = np.hstack([phi * n, constants.zeros_3, constants.identity_6x1])
        gw.dump_grain(i, 1, 0, grain_params)
    gw.close()
    return grains_table


def write_grains_txt(grains_table: Any, filename: str) -> None:
    gw = instrument.GrainDataWriter(filename=filename)
    try:
        for grain in grains_table:
            gw.dump_grain(grain[0], grain[1], grain[2], grain[3:15])
    finally:
        gw.close()


def hkl_in_list(hkl: Any, hkl_list: Any) -> bool:
    def hkls_equal(hkl_a: Any, hkl_b: Any) -> bool:
        return all(x == y for x, y in zip(hkl_a, hkl_b))

    for hkl_b in hkl_list:
        if hkls_equal(hkl, hkl_b):
            return True

    return False


def hkls_missing_in_list(hkls: Any, hkl_list: Any) -> list:
    missing = []
    for hkl in hkls:
        if not hkl_in_list(hkl, hkl_list):
            missing.append(hkl)

    return missing
