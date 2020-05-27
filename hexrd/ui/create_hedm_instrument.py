from hexrd.instrument import HEDMInstrument

from hexrd.ui.hexrd_config import HexrdConfig


def create_hedm_instrument():
    # HEDMInstrument expects None Euler angle convention for the
    # config. Let's get it as such.
    iconfig = HexrdConfig().instrument_config_none_euler_convention
    rme = HexrdConfig().rotation_matrix_euler()

    return HEDMInstrument(instrument_config=iconfig,
                          tilt_calibration_mapping=rme)
