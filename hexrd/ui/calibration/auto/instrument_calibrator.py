import numpy as np

from lmfit import Minimizer, Parameters
from scipy.optimize import leastsq, least_squares


class InstrumentCalibrator(object):
    def __init__(self, *args):
        """
        Model for instrument calibration class as a function of

        Parameters
        ----------
        *args : TYPE
            DESCRIPTION.

        Returns
        -------
        None.

        Notes
        -----
        Flags are set on calibrators
        """
        assert len(args) > 0, \
            "must have at least one calibrator"
        self._calibrators = args
        self._instr = self._calibrators[0].instr
        self.npi = len(self._instr.calibration_parameters)
        self.full_params = self._instr.calibration_parameters
        for calib in self._calibrators:
            assert calib.instr is self._instr, \
                "all calibrators must refer to the same instrument"
            self.full_params = np.hstack([self.full_params, calib.params])

    @property
    def instr(self):
        return self._instr

    @property
    def calibrators(self):
        return self._calibrators

    @property
    def flags(self):
        # additional params come next
        flags = [self.instr.calibration_flags, ]
        for calib_class in self.calibrators:
            flags.append(calib_class.flags[calib_class.npi:])
        return np.hstack(flags)

    @property
    def reduced_params(self):
        return self.full_params[self.flags]

    # =========================================================================
    # METHODS
    # =========================================================================

    def _reduced_params_flag(self, cidx):
        assert cidx >= 0 and cidx < len(self.calibrators), \
            "index must be in %s" % str(np.arange(len(self.calibrators)))

        calib_class = self.calibrators[cidx]

        # instrument params come first
        npi = calib_class.npi

        # additional params come next
        cparams_flags = [calib_class.flags[:npi], ]
        for i, calib_class in enumerate(self.calibrators):
            if i == cidx:
                cparams_flags.append(calib_class.flags[npi:])
            else:
                cparams_flags.append(np.zeros(calib_class.npe, dtype=bool))
        return np.hstack(cparams_flags)

    def extract_points(self, fit_tth_tol, int_cutoff=1e-4):
        # !!! list in the same order as dict looping
        master_data_dict_list = []
        for calib_class in self.calibrators:
            master_data_dict_list.append(
                calib_class._extract_powder_lines(
                    fit_tth_tol=fit_tth_tol, int_cutoff=int_cutoff
                )
            )
        return master_data_dict_list

    def residual(self, x0, master_data_dict_list):
        # !!! list in the same order as dict looping
        resd = []
        for i, calib_class in enumerate(self.calibrators):
            # !!! need to grab the param set
            #     specific to this calibrator class
            fp = np.array(self.full_params)  # copy full_params
            fp[self.flags] = x0  # assign new global values
            this_x0 = fp[self._reduced_params_flag(i)]  # select these
            resd.append(
                calib_class.residual(
                    this_x0,
                    master_data_dict_list[i]
                )
            )
        return np.hstack(resd)

    def run_calibration(self,
                        fit_tth_tol=None, int_cutoff=1e-4,
                        conv_tol=1e-4, max_iter=5,
                        use_robust_optimization=False):
        """


        Parameters
        ----------
        fit_tth_tol : TYPE, optional
            DESCRIPTION. The default is None.
        int_cutoff : TYPE, optional
            DESCRIPTION. The default is 1e-4.
        conv_tol : TYPE, optional
            DESCRIPTION. The default is 1e-4.
        max_iter : TYPE, optional
            DESCRIPTION. The default is 5.
        use_robust_optimization : TYPE, optional
            DESCRIPTION. The default is False.

        Returns
        -------
        x1 : TYPE
            DESCRIPTION.

        """

        delta_r = np.inf
        step_successful = True
        iter_count = 0
        while delta_r > conv_tol \
            and step_successful \
                and iter_count <= max_iter:

            # extract data
            master_data_dict_list = self.extract_points(
                fit_tth_tol=fit_tth_tol,
                int_cutoff=int_cutoff
            )

            # grab reduced params for optimizer
            x0 = np.array(self.reduced_params)  # !!! copy
            resd0 = self.residual(x0, master_data_dict_list)

            if use_robust_optimization:
                if isinstance(use_robust_optimization, bool):
                    oresult = least_squares(
                        self.residual,
                        x0, args=(master_data_dict_list, ),
                        method='trf', loss='soft_l1'
                    )
                    x1 = oresult['x']
                else:
                    params = Parameters()  # noqa: F841
                    lm = Minimizer()  # noqa: F841
            else:
                x1, cox_x, infodict, mesg, ierr = leastsq(
                    self.residual,
                    x0, args=(master_data_dict_list, ),
                    full_output=True
                )
            resd1 = self.residual(x1, master_data_dict_list)

            delta_r = sum(resd0**2)/float(len(resd0)) - \
                sum(resd1**2)/float(len(resd1))

            if delta_r > 0:
                print('OPTIMIZATION SUCCESSFUL!!!')
                print('Change in residual: '
                      f'{delta_r}')
            else:
                print('no improvement in residual!!!')
                step_successful = False

            print('initial ssr: '
                  f'{sum(resd0**2)/float(len(resd0))}')
            print('final ssr: '
                  f'{sum(resd1**2)/float(len(resd1))}')

            iter_count += 1

        return x1
