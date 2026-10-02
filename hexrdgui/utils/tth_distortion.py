import numpy as np


def apply_tth_distortion_if_needed(
    ang_crds: np.ndarray,
    in_degrees: bool = False,
    reverse: bool = False,
) -> np.ndarray:
    from hexrdgui.hexrd_config import HexrdConfig

    # The ang_crds is a numpy array of angular coordinates
    # in_degrees indicates whether the polar data is in degrees or not
    # If reverse is true, then the distortion is applied in the opposite
    # direction.

    # First, check if we are actually applying tth distortion.
    # If we are not, just skip and return.
    distortion_object = HexrdConfig().polar_tth_distortion_object
    polar_corr_field = HexrdConfig().polar_corr_field_polar
    polar_angular_grid = HexrdConfig().polar_angular_grid

    skip = (
        distortion_object is None
        or polar_corr_field is None
        or polar_angular_grid is None
    )
    if skip:
        # We are not applying tth distortion. Just return.
        return ang_crds

    # Set up the variables we need
    assert polar_corr_field is not None
    assert polar_angular_grid is not None
    polar_field = polar_corr_field.filled(np.nan)
    eta_centers, tth_centers = polar_angular_grid
    first_eta_col = eta_centers[:, 0]
    first_tth_row = tth_centers[0]

    def offset_at(tth: float, eta: float) -> float:
        i = np.argmin(np.abs(tth - first_tth_row))
        j = np.argmin(np.abs(eta - first_eta_col))
        return polar_field[j, i]

    if in_degrees:
        ang_crds = np.radians(ang_crds)

    for ic, (tth, eta) in enumerate(ang_crds):
        if not reverse:
            ang_crds[ic, 0] = tth + offset_at(tth, eta)
            continue

        # The offset is defined at the undistorted angle, which is what we
        # are solving for. Iterate, starting from the distorted angle.
        nominal = tth
        for _ in range(10):
            previous = nominal
            nominal = tth - offset_at(nominal, eta)
            if not np.isfinite(nominal) or abs(nominal - previous) < 1e-9:
                break
        ang_crds[ic, 0] = nominal

    if in_degrees:
        ang_crds = np.degrees(ang_crds)

    return ang_crds
