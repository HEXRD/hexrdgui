import numpy as np

from scipy.optimize import minimize
from scipy import stats

from hexrd import instrument

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.utils import convert_tilt_convention
from hexrd.ui.utils import remove_none_distortions

# =============================================================================
# %% Functions and parameters
# =============================================================================


def process_angular_picks(tth_eta_rings, instr, output_pixels=False):
    cartesian_picks = []
    for iring, ring in enumerate(tth_eta_rings):
        cartesian_picks.append(dict.fromkeys(instr.detectors))
        for det_key, panel in instr.detectors.items():
            det_xy = panel.clip_to_panel(
                panel.angles_to_cart(
                    np.radians(ring)
                )
            )[0]
            if output_pixels:
                det_xy = panel.cartToPixel(det_xy, pixels=True)
            cartesian_picks[iring][det_key] = det_xy
    return cartesian_picks


def obj_function(reduced_params, instr, ring_xy):
    full_params = instr.calibration_parameters
    full_params[instr.calibration_flags] = reduced_params
    instr.update_from_parameter_list(full_params)
    residual = 0.
    for ring in ring_xy:
        rtth = []
        for det_key, panel in instr.detectors.items():
            if len(ring[det_key]) > 0:
                rtth.append(panel.cart_to_angles(ring[det_key])[0][:, 0])
        residual += stats.variation(np.hstack(rtth))
    return residual


def calibrate_instrument_from_picks(
        instr, ring_pts, tilt_conversion=None,
        param_flags=None, xtol=1e-4, ftol=1e-4):
    """
    arguments xyo_det, hkls_idx are DICTs over panels

    !!!
        distortion is still hosed...
        Currently a dict of detector keys with
        distortion[key] = [d_func, d_params, d_flags]
    """
    pnames = [
        '{:>24s}'.format('wavelength'),
        '{:>24s}'.format('beam azimuth'),
        '{:>24s}'.format('beam polar angle'),
        '{:>24s}'.format('chi'),
        '{:>24s}'.format('tvec_s[0]'),
        '{:>24s}'.format('tvec_s[1]'),
        '{:>24s}'.format('tvec_s[2]'),
    ]

    for det_key, panel in instr.detectors.items():
        pnames += [
            '{:>24s}'.format('%s tilt[0]' % det_key),
            '{:>24s}'.format('%s tilt[1]' % det_key),
            '{:>24s}'.format('%s tilt[2]' % det_key),
            '{:>24s}'.format('%s tvec[0]' % det_key),
            '{:>24s}'.format('%s tvec[1]' % det_key),
            '{:>24s}'.format('%s tvec[2]' % det_key),
        ]

    # tilt conversion
    if tilt_conversion is not None:
        instr.tilt_calibration_mapping = tilt_conversion

    # now add distortion if
    for det_key, panel in instr.detectors.items():
        if panel.distortion is not None:
            for j in range(len(panel.distortion[1])):
                pnames.append(
                    '{:>24s}'.format('%s dparam[%d]' % (det_key, j))
                )

    # reset parameter flags for instrument as specified
    if param_flags is None:
        param_flags = instr.calibration_flags
    else:
        # will throw an AssertionError if wrong length
        instr.calibration_flags = param_flags

    # full parameter list
    x0 = instr.calibration_parameters[instr.calibration_flags]
    fit_args = (instr, process_angular_picks(ring_pts, instr))

    print("Set up to refine:")
    for i in np.where(param_flags)[0]:
        print("\t%s = %1.7e" % (pnames[i], instr.calibration_parameters[i]))

    # run optimization
    # scipy.optimize.minimize(
    #         fun, x0, args=(),
    #         method=None, jac=None,
    #         hess=None, hessp=None,
    #         bounds=None, constraints=(),
    #         tol=None, callback=None,
    #         options=None)
    #
    # obj_function(reduced_params, instr, ring_points)
    options = {
        'xatol': xtol,
        'fatol': ftol
    }
    result = minimize(
        obj_function, x0, args=fit_args,
        method='Nelder-Mead', options=options
    )
    mesg = result.message
    success = result.success
    ierr = result.status

    if not success:
        raise RuntimeError(
            "solution not found: ierr = %d and message '%s'"
            % (ierr, mesg)
        )
    else:
        print("INFO: optimization fininshed successfully with ierr=%d"
              % ierr)
        print("INFO: %s" % mesg)
        print("Refined parameters:")
        for i in np.where(param_flags)[0]:
            print("\t%s = %1.7e"
                  % (pnames[i], instr.calibration_parameters[i]))
    return result


def run_line_picked_calibration(line_data):
    # Set up the tilt calibration mapping
    rme = HexrdConfig().rotation_matrix_euler()

    print('Setting up the instrument...')

    # Set up the instrument
    iconfig = HexrdConfig().instrument_config_none_euler_convention
    remove_none_distortions(iconfig)
    instr = instrument.HEDMInstrument(instrument_config=iconfig,
                                      tilt_calibration_mapping=rme)

    flags = HexrdConfig().get_statuses_instrument_format()

    if np.count_nonzero(flags) == 0:
        msg = 'There are no refinable parameters'
        raise Exception(msg)

    if len(flags) != len(instr.calibration_flags):
        msg = 'Length of internal flags does not match instr.calibration_flags'
        raise Exception(msg)

    print('Running optimization...')

    # Run calibration
    opt_result = calibrate_instrument_from_picks(instr, line_data,
                                                 param_flags=flags, xtol=1e-4,
                                                 ftol=1e-4)

    if not opt_result.success:
        print('Optimization failed!')
        return False

    print('Optimization succeeded!')

    # Add this so the calibration crystal gets written
    cal_crystal = iconfig.get('calibration_crystal')
    output_dict = instr.write_config(calibration_dict=cal_crystal)

    # Convert back to whatever convention we were using before
    eac = HexrdConfig().euler_angle_convention
    if eac != (None, None):
        old_conv = (None, None)
        convert_tilt_convention(output_dict, old_conv, eac)

    # Add the saturation levels, as they seem to be missing
    sl = 'saturation_level'
    for det in output_dict['detectors'].keys():
        output_dict['detectors'][det][sl] = iconfig['detectors'][det][sl]

    print('Updating the config')

    # Save the previous iconfig to restore the statuses
    prev_iconfig = HexrdConfig().config['instrument']

    # Update the config
    HexrdConfig().config['instrument'] = output_dict

    # This adds in any missing keys. In particular, it is going to
    # add in any "None" detector distortions
    HexrdConfig().set_detector_defaults_if_missing()

    # Add status values
    HexrdConfig().add_status(output_dict)

    # Set the previous statuses to be the current statuses
    HexrdConfig().set_statuses_from_prev_iconfig(prev_iconfig)

    return True
