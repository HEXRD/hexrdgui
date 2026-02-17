from matplotlib.path import Path
import numpy as np

igor_marker = Path(
    **{  # type: ignore[arg-type]
        'vertices': np.array(
            [
                [-16.48574545, -28.6460785],
                [33.00703639, 57.0779395],
                [32.86758639, -28.1361335],
                [-16.41738645, 56.9964295],
                [-16.48574545, -28.6460785],
                [-16.48574545, -28.6460785],
            ]
        ),
        'codes': np.array([1, 2, 2, 2, 2, 79], dtype=np.uint8),
    }
)
