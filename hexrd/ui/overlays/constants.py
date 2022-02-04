import numpy as np

from hexrd import constants


def default_crystal_params():
    return np.hstack(
        [constants.zeros_3, constants.zeros_3, constants.identity_6x1])


def default_crystal_refinements():
    refine_indices = [0, 1, 2]  # Only refine these by default
    return np.asarray([i in refine_indices for i in range(12)])


def crystal_refinement_labels():
    inverse_matrix_strings = [
        '0_0',
        '1_1',
        '2_2',
        '1_2',
        '0_2',
        '0_1'
    ]

    items = [f'orientation_{i}' for i in range(3)]
    items += [f'position_{i}' for i in range(3)]
    items += [f'stretch_{x}' for x in inverse_matrix_strings]
    return items
