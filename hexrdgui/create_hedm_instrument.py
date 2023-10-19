from hexrd import constants as ct
from hexrd.instrument import HEDMInstrument

from hexrdgui.constants import ViewType
from hexrdgui.hexrd_config import HexrdConfig


def create_hedm_instrument():
    # Ensure that the panel buffer sizes match the pixel sizes.
    # If not, clear the panel buffer and print a warning.
    # It would be nice to avoid this check, but it is sometimes difficult to
    # track down all of the places where there may be a synchronization issue.
    # When there is a synchronization issue, it typically messes up the whole
    # program. So keep this check here unless we find out a better way.
    HexrdConfig().clean_panel_buffers()

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


def create_view_hedm_instrument():
    # Some views use a modified version of the HEDM instrument.
    # This ensures the correct instrument for the view is used.
    instr = create_hedm_instrument()
    if HexrdConfig().image_mode == ViewType.stereo:
        # Set the beam vector for the VISAR view
        instr.beam_vector = ct.beam_vec

    return instr
