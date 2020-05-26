from hexrd.instrument.beam import Beam
from hexrd.instrument.detector import PlanarDetector
from hexrd.instrument.instrument import HEDMInstrument
from hexrd.instrument.oscillation_stage import OscillationStage

from hexrd.instrument.instrument import eta_vec_DFLT

from hexrd.ui.hexrd_config import HexrdConfig


def create_hedm_instrument():
    # Takes the current config and creates an HEDMInstrument from it
    kwargs = {}

    # HEDMInstrument expects None Euler angle convention for the
    # config. Let's get it as such.
    iconfig = HexrdConfig().instrument_config_none_euler_convention
    kwargs['tilt_calibration_mapping'] = HexrdConfig().rotation_matrix_euler()

    kwargs['beam'] = create_beam(iconfig)
    kwargs['eta_vector'] = eta_vec_DFLT
    kwargs['detector_dict'] = create_detector_dict(
        iconfig, beam=kwargs['beam'], eta_vector=kwargs['eta_vector'])

    kwargs['oscillation_stage'] = create_oscillation_stage(iconfig)
    kwargs['instrument_name'] = None

    return HEDMInstrument(**kwargs)


def create_beam(iconfig):
    # Use kwargs so the default is used when unspecified.
    kwargs = {}

    # EAFP
    try:
        kwargs['energy'] = iconfig['beam']['energy']
    except KeyError:
        pass

    try:
        azimuth = iconfig['beam']['vector']['azimuth']
        polar_angle = iconfig['beam']['vector']['polar_angle']
    except KeyError:
        pass
    else:
        kwargs['vector'] = Beam.calc_beam_vec(azimuth, polar_angle)

    return Beam(**kwargs)


def create_oscillation_stage(iconfig):
    kwargs = {}

    # EAFP
    try:
        kwargs['tvec'] = iconfig['oscillation_stage']['translation']
    except KeyError:
        pass

    try:
        kwargs['chi'] = iconfig['oscillation_stage']['chi']
    except KeyError:
        pass

    return OscillationStage(**kwargs)


def create_distortion_dict(iconfig):
    detectors = iconfig.get('detectors', {})

    # This might need to be changed in the future...
    from hexrd.distortion import GE_41RT

    dist_func_map = {
        'GE41RT': GE_41RT,
        'GE_41RT': GE_41RT
    }

    # Have default values of None
    distortion_dict = {key: None for key in detectors.keys()}
    for key, det in detectors.items():
        try:
            func_name = det['distortion']['function_name']
            parameters = det['distortion']['parameters']

            if func_name == 'None':
                continue

            if func_name not in dist_func_map:
                print('Warning:', func_name, 'is not a known distortion'
                      'function. Skipping it')
                continue

            distortion_dict[key] = [dist_func_map[func_name], parameters]

        except KeyError:
            continue

    return distortion_dict


def create_detector_dict(iconfig, beam, eta_vector=eta_vec_DFLT):
    distortion_dict = create_distortion_dict(iconfig)
    detectors = iconfig.get('detectors', {})

    ret = {}
    for key, det in detectors.items():
        try:
            pix = det['pixels']
            xform = det['transform']

            kwargs = {
                'rows': pix['rows'],
                'cols': pix['columns'],
                'pixel_size': pix['size'],
                'tvec': xform['translation'],
                'tilt': xform['tilt'],
                'name': key,
                'evec': eta_vector,
                'saturation_level': det.get('saturation_level'),
                'panel_buffer': det.get('buffer'),
                'roi': None,
                'distortion': distortion_dict[key],
                'beam': beam
            }
        except KeyError as e:
            print('Warning: key', e, 'was missing in the detector config for',
                  key, '\nSkipping over it in instrument creation.')
        else:
            ret[key] = PlanarDetector(**kwargs)

    return ret
