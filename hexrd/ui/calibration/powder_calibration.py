import numpy as np

from scipy.optimize import leastsq, least_squares

from hexrd import instrument
from hexrd.matrixutil import findDuplicateVectors
from hexrd.fitting import fitpeak

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.utils import convert_tilt_convention


class InstrumentCalibrator(object):
    def __init__(self, *args):
        assert len(args) > 0, \
            "must have at least one calibrator"
        self._calibrators = args
        self._instr = self._calibrators[0].instr

    @property
    def instr(self):
        return self._instr

    @property
    def calibrators(self):
        return self._calibrators

    # =========================================================================
    # METHODS
    # =========================================================================

    def run_calibration(self, use_robust_optimization=False):
        """
        FIXME: only coding serial powder case to get things going.  Will
        eventually figure out how to loop over multiple calibrator classes.
        All will have a reference the same instrument, but some -- like single
        crystal -- will have to add parameters as well as contribute to the RHS
        """
        calib_class = self.calibrators[0]

        obj_func = calib_class.residual

        data_dict = calib_class._extract_powder_lines()

        # grab reduced optimizaion parameter set
        x0 = self._instr.calibration_parameters[
                self._instr.calibration_flags
            ]

        resd0 = obj_func(x0, data_dict)

        if use_robust_optimization:
            oresult = least_squares(
                obj_func, x0, args=(data_dict, ),
                method='trf', loss='soft_l1'
            )
            x1 = oresult['x']
        else:
            x1, cox_x, infodict, mesg, ierr = leastsq(
                obj_func, x0, args=(data_dict, ),
                full_output=True
            )
        resd1 = obj_func(x1, data_dict)

        delta_r = sum(resd0**2)/float(len(resd0)) - \
            sum(resd1**2)/float(len(resd1))

        if delta_r > 0:
            print(('OPTIMIZATION SUCCESSFUL\nfinal ssr: %f' % sum(resd1**2)))
            print(('delta_r: %f' % delta_r))
            # self.instr.write_config(instrument_filename)
        else:
            print('no improvement in residual!!!')


# %%
class PowderCalibrator(object):
    def __init__(self, instr, plane_data, img_dict,
                 tth_tol=None, eta_tol=0.25,
                 pktype='pvoigt'):
        assert list(instr.detectors.keys()) == list(img_dict.keys()), \
            "instrument and image dict must have the same keys"
        self._instr = instr
        self._plane_data = plane_data
        self._img_dict = img_dict

        # for polar interpolation
        self._tth_tol = tth_tol or np.degrees(plane_data.tThWidth)
        self._eta_tol = eta_tol

        # for peak fitting
        # ??? fitting only, or do alternative peak detection?
        self._pktype = pktype

    @property
    def instr(self):
        return self._instr

    @property
    def plane_data(self):
        return self._plane_data

    @property
    def img_dict(self):
        return self._img_dict

    @property
    def tth_tol(self):
        return self._tth_tol

    @tth_tol.setter
    def tth_tol(self, x):
        assert np.isscalar(x), "tth_tol must be a scalar value"
        self._tth_tol = x

    @property
    def eta_tol(self):
        return self._eta_tol

    @eta_tol.setter
    def eta_tol(self, x):
        assert np.isscalar(x), "eta_tol must be a scalar value"
        self._eta_tol = x

    @property
    def pktype(self):
        return self._pktype

    @pktype.setter
    def pktype(self, x):
        """
        currently only 'pvoigt' or 'gaussian'
        """
        assert isinstance(x, str), "tth_tol must be a scalar value"
        self._pktype = x

    def _interpolate_images(self):
        """
        returns the iterpolated powder line data from the images in img_dict

        ??? interpolation necessary?
        """
        return self.instr.extract_line_positions(
                self.plane_data, self.img_dict,
                tth_tol=self.tth_tol, eta_tol=self.eta_tol,
                npdiv=2, collapse_eta=False, collapse_tth=False,
                do_interpolation=True)

    def _extract_powder_lines(self):
        """
        return the RHS for the instrument DOF and image dict

        The format is a dict over detectors, each containing

        [index over ring sets]
            [index over azimuthal patch]
                [xy_meas, tth_meas, tth_ref, eta_ref]

        FIXME: can not yet handle tth ranges with multiple peaks!
        """
        # ideal tth
        tth_ideal = self.plane_data.getTTh()
        tth0 = []
        for idx in self.plane_data.getMergedRanges()[0]:
            if len(idx) > 1:
                eqv, uidx = findDuplicateVectors(np.atleast_2d(tth_ideal[idx]))
                if len(uidx) > 1:
                    raise NotImplementedError("can not handle multipeak yet")
                else:
                    # if here, only degenerate ring case
                    uidx = idx[0]
            else:
                uidx = idx[0]
            tth0.append(tth_ideal[uidx])

        powder_lines = self._interpolate_images()

        # GRAND LOOP OVER PATCHES
        rhs = dict.fromkeys(self.instr.detectors)
        for det_key, panel in self.instr.detectors.items():
            rhs[det_key] = []
            for i_ring, ringset in enumerate(powder_lines[det_key]):
                tmp = []
                for angs, intensities in ringset:
                    tth_centers = np.average(
                        np.vstack([angs[0][:-1], angs[0][1:]]),
                        axis=0)
                    eta_ref = angs[1]
                    int1d = np.sum(np.array(intensities).squeeze(), axis=0)
                    """
                    DARREN: FIT [tth_centers, intensities[0]] HERE

                    RETURN TTH0
                    rhs.append([tth0, eta_ref])
                    """
                    p0 = fitpeak.estimate_pk_parms_1d(
                            tth_centers, int1d, self.pktype
                         )

                    p = fitpeak.fit_pk_parms_1d(
                            p0, tth_centers, int1d, self.pktype
                        )
                    # !!! this is where we can kick out bunk fits
                    tth_meas = p[1]
                    center_err = abs(tth_meas - tth0[i_ring])
                    if p[0] < 0.1 or center_err > np.radians(self.tth_tol):
                        continue
                    xy_meas = panel.angles_to_cart([[tth_meas, eta_ref], ])

                    # distortion
                    if panel.distortion is not None:
                        xy_meas = panel.distortion.apply_inverse(xy_meas)

                    # cat results
                    tmp.append(
                        np.hstack(
                            [xy_meas.squeeze(),
                             tth_meas,
                             tth0[i_ring],
                             eta_ref]
                        )
                    )
                    pass
                rhs[det_key].append(np.vstack(tmp))
                pass
            rhs[det_key] = np.vstack(rhs[det_key])
            pass
        return rhs

    def residual(self, reduced_params, data_dict):
        """
        """

        # first update instrument from input parameters
        full_params = self.instr.calibration_parameters
        full_params[self.instr.calibration_flags] = reduced_params
        self.instr.update_from_parameter_list(full_params)

        # build residual
        resd = []
        for det_key, panel in self.instr.detectors.items():
            pdata = np.vstack(data_dict[det_key])
            if len(pdata) > 0:
                calc_xy = panel.angles_to_cart(pdata[:, -2:])

                # distortion
                if panel.distortion is not None:
                    calc_xy = panel.distortion.apply_inverse(calc_xy)

                resd.append(
                    (pdata[:, :2].flatten() - calc_xy.flatten())
                )
            else:
                continue
        return np.hstack(resd)


def run_powder_calibration():
    # Set up the tilt calibration mapping
    rme = HexrdConfig().rotation_matrix_euler()

    # Set up the instrument
    iconfig = HexrdConfig().instrument_config_none_euler_convention
    instr = instrument.HEDMInstrument(instrument_config=iconfig,
                                      tilt_calibration_mapping=rme)

    flags = HexrdConfig().get_statuses_instrument_format()

    if len(flags) != len(instr.calibration_flags):
        msg = 'Length of internal flags does not match instr.calibration_flags'
        raise Exception(msg)

    instr.calibration_flags = flags

    # Plane data and images
    plane_data = HexrdConfig().active_material.planeData
    img_dict = HexrdConfig().current_images_dict()

    # tolerances for patches
    tth_tol = HexrdConfig().config['calibration']['powder']['tth_tol']
    eta_tol = HexrdConfig().config['calibration']['powder']['eta_tol']
    pktype = HexrdConfig().config['calibration']['powder']['pk_type']

    # powder calibrator
    pc = PowderCalibrator(instr, plane_data, img_dict,
                          tth_tol=tth_tol, eta_tol=eta_tol,
                          pktype=pktype)

    # make instrument calibrator
    ic = InstrumentCalibrator(pc)

    use_robust_optimization = False
    ic.run_calibration(use_robust_optimization)

    # We might need to use this at some point
    # data_dict = pc._extract_powder_lines()

    # Add this so the calibration crystal gets written
    cal_crystal = iconfig.get('calibration_crystal')
    output_dict = instr.write_config(calibration_dict=cal_crystal)

    # Convert back to whatever convention we were using before
    eac = HexrdConfig().euler_angle_convention
    if eac is not None:
        convert_tilt_convention(output_dict, None, eac)

    # Add the saturation levels, as they seem to be missing
    sl = 'saturation_level'
    for det in output_dict['detectors'].keys():
        output_dict['detectors'][det][sl] = iconfig['detectors'][det][sl]

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
