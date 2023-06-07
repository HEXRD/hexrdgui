import numpy as np


def apply_tth_distortion_if_needed(ang_crds, in_degrees=False, reverse=False):
    from hexrd.ui.hexrd_config import HexrdConfig

    # The ang_crds is a numpy array of angular coordinates
    # in_degrees indicates whether the polar data is in degrees or not
    # If reverse is true, then the distortion is applied in the opposite
    # direction.
    multiplier = -1 if reverse else 1

    # First, check if we are actually applying tth distortion.
    # If we are not, just skip and return.
    distortion_object = HexrdConfig().polar_tth_distortion_object
    polar_corr_field = HexrdConfig().polar_corr_field_polar
    polar_angular_grid = HexrdConfig().polar_angular_grid

    skip = (
        distortion_object is None or
        polar_corr_field is None or
        polar_angular_grid is None
    )
    if skip:
        # We are not applying tth distortion. Just return.
        return ang_crds

    # Set up the variables we need
    polar_field = polar_corr_field.filled(np.nan)
    eta_centers, tth_centers = polar_angular_grid
    first_eta_col = eta_centers[:, 0]
    first_tth_row = tth_centers[0]

    # Compute and apply offset in reverse
    if in_degrees:
        ang_crds = np.radians(ang_crds)

    for ic, ang_crd in enumerate(ang_crds):
        i = np.argmin(np.abs(ang_crd[0] - first_tth_row))
        j = np.argmin(np.abs(ang_crd[1] - first_eta_col))
        ang_crds[ic, 0] += (polar_field[j, i] * multiplier)

    if in_degrees:
        ang_crds = np.degrees(ang_crds)

    return ang_crds
