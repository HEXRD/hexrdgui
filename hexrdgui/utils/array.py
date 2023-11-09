import numpy as np


def split_array(x, indices, axis=0):
    # Split an array into two subarrays:
    # the first containing the values at the indices,
    # and the second containing the values *not* at the indices.
    try:
        # This is faster than the list version
        taken = np.take(x, indices, axis=axis)
        deleted = np.delete(x, indices, axis=axis)
    except ValueError:
        # The list version might take longer
        taken = [x for i, x in enumerate(x) if i in indices]
        deleted = [x for i, x in enumerate(x) if i not in indices]

    return taken, deleted
