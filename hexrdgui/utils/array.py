from typing import Any

import numpy as np


def split_array(x: Any, indices: Any, axis: int = 0) -> tuple[Any, Any]:
    # Split an array into two subarrays:
    # the first containing the values at the indices,
    # and the second containing the values *not* at the indices.
    try:
        # This is faster than the list version
        taken: Any = np.take(x, indices, axis=axis)
        deleted: Any = np.delete(x, indices, axis=axis)
    except ValueError:
        # The list version might take longer
        taken = [x for i, x in enumerate(x) if i in indices]
        deleted = [x for i, x in enumerate(x) if i not in indices]

    return taken, deleted
