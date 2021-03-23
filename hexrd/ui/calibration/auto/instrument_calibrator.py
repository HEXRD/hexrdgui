import numpy as np

from lmfit import Minimizer, Parameters
from scipy.optimize import leastsq, least_squares


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

    def run_calibration(self,
                        conv_tol=1e-4, fit_tth_tol=None, max_iter=5,
                        use_robust_optimization=False):
        """
        FIXME: only coding serial powder case to get things going.  Will
        eventually figure out how to loop over multiple calibrator classes.
        All will have a reference the same instrument, but some -- like single
        crystal -- will have to add parameters as well as contribute to the RHS
        """
        calib_class = self.calibrators[0]

        obj_func = calib_class.residual

        delta_r = np.inf
        step_successful = True
        iter_count = 0
        while delta_r > conv_tol \
            and step_successful \
                and iter_count <= max_iter:
            data_dict = calib_class._extract_powder_lines(
                fit_tth_tol=fit_tth_tol)

            # grab reduced optimizaion parameter set
            x0 = self._instr.calibration_parameters[
                self._instr.calibration_flags
            ]

            resd0 = obj_func(x0, data_dict)

            if use_robust_optimization:
                if isinstance(use_robust_optimization, bool):
                    oresult = least_squares(
                        obj_func, x0, args=(data_dict, ),
                        method='trf', loss='soft_l1'
                    )
                    x1 = oresult['x']
                else:
                    params = Parameters()  # noqa: F841
                    lm = Minimizer()  # noqa: F841
            else:
                x1, cox_x, infodict, mesg, ierr = leastsq(
                    obj_func, x0, args=(data_dict, ),
                    full_output=True
                )
            resd1 = obj_func(x1, data_dict)

            delta_r = sum(resd0**2)/float(len(resd0)) - \
                sum(resd1**2)/float(len(resd1))

            if delta_r > 0:
                print('OPTIMIZATION SUCCESSFUL\nfinal ssr: '
                      f'{sum(resd1**2)/float(len(resd1))}')
                print(f'delta_r: {delta_r}')
            else:
                print('no improvement in residual!!!')
                step_successful = False

            iter_count += 1

        return x1
