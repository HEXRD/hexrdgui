from hexrd.instrument import HEDMInstrument

from hexrd.ui.hexrd_config import HexrdConfig


def create_hedm_instrument():
    # HEDMInstrument expects None Euler angle convention for the
    # config. Let's get it as such.
    iconfig = HexrdConfig().instrument_config_none_euler_convention
    kwargs = {
        'instrument_config': iconfig,
        'tilt_calibration_mapping': HexrdConfig().rotation_matrix_euler(),
    }

    if HexrdConfig().max_cpus is not None:
        kwargs['max_workers'] = HexrdConfig().max_cpus

    return HEDMInstrument(**kwargs)
