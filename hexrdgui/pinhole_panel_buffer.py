import numpy as np


def generate_pinhole_panel_buffer(instr):
    ph_buffer = {}

    # Save the beam vector so we can restore it later
    prev_beam_vector = instr.beam_vector

    physics_package = instr.physics_package

    # make beam vector the pinhole axis on the instrument
    instr.beam_vector = np.r_[0., 0., -1.]
    try:
        for det_key, det in instr.detectors.items():
            crit_angle = np.arctan(
                physics_package.pinhole_radius /
                physics_package.pinhole_thickness)
            ptth, peta = det.pixel_angles()
            ph_buffer[det_key] = ptth < crit_angle
    finally:
        instr.beam_vector = prev_beam_vector

    return ph_buffer
