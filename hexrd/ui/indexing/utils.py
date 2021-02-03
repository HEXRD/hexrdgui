import numpy as np

from hexrd import constants
from hexrd import instrument
from hexrd.transforms import xfcapi


def generate_grains_table(qbar):
    num_grains = qbar.shape[1]
    grains_table = np.empty((num_grains, 21))
    gw = instrument.GrainDataWriter(array=grains_table)
    for i, q in enumerate(qbar.T):
        phi = 2 * np.arccos(q[0])
        n = xfcapi.unitRowVector(q[1:])
        grain_params = np.hstack(
            [phi * n, constants.zeros_3, constants.identity_6x1]
        )
        gw.dump_grain(i, 1, 0, grain_params)
    gw.close()
    return grains_table
