import numpy as np
from scipy.optimize import leastsq

from hexrd.fitting.calibration import CompositeCalibration


def enrich_pick_data(picks, instr, materials):
    # add plane_data, xy points from angles...
    data_key = 'pick_xys'
    for pick_data in picks:
        # need plane data
        material_name = pick_data['material']
        plane_data = materials[material_name].planeData
        pick_data['plane_data'] = plane_data

        # now add additional data depending on pick type
        pick_dict = pick_data['picks']
        pick_type = pick_data['type']

        # loop over detectors
        pick_data[data_key] = dict.fromkeys(pick_dict)
        for det_key, panel in instr.detectors.items():
            if pick_type == 'laue':
                # need grain parameters and stacked picks
                grain_params = pick_data['options']['crystal_params']
                tth_eta_picks = pick_dict[det_key]
                if len(tth_eta_picks) == 0:
                    tth_eta_picks = np.empty((0, 2))
                    pick_data[data_key][det_key] = np.empty((0, 2))
                else:
                    # calculate cartesian coords
                    tth_eta_picks = np.vstack(tth_eta_picks)
                    xy_picks = panel.angles_to_cart(
                        np.radians(tth_eta_picks),
                        tvec_c=np.asarray(grain_params[3:6], dtype=float)
                    )
                    pick_data[data_key][det_key] = xy_picks
            elif pick_type == 'powder':
                # !!! need translation vector from overlay
                tvec_c = np.asarray(
                    pick_data['options']['tvec'], dtype=float
                ).flatten()

                # calculate cartesian coords
                # !!! uses translation vector
                pdl = []
                for ring_picks in pick_dict[det_key]:
                    if len(ring_picks) > 0:
                        xy_picks = panel.angles_to_cart(
                            np.atleast_2d(np.radians(ring_picks)),
                            tvec_c=tvec_c
                        )
                    else:
                        xy_picks = []
                    pdl.append(xy_picks)
                pick_data[data_key][det_key] = pdl


def run_calibration(picks, instr, img_dict, materials):
    enrich_pick_data(picks, instr, materials)

    # Run composite calibration
    instr_calibrator = CompositeCalibration(instr, picks, img_dict)

    x0_comp = instr_calibrator.reduced_params()

    # Compute resd0, as hexrd does
    resd0 = instr_calibrator.residual(x0_comp, picks)  # noqa: F841

    x1, cox_x, infodict, mesg, ierr = leastsq(
                        instr_calibrator.residual, x0_comp, args=(picks, ),
                        full_output=True
                )

    # Evaluate new residual
    # This will update the parameters
    resd1 = instr_calibrator.residual(x1, picks)  # noqa: F841

    return instr_calibrator


if __name__ == '__main__':

    import json
    import pickle as pkl

    # %% grab serialiazed objects
    instr = pkl.load(open('instrument.pkl', 'rb'))

    with open('calibration_picks.json', 'r') as f:
        picks = json.load(f)

    material_names = [x['material'] for x in picks]
    materials = {x: pkl.load(open(f'{x}.pkl', 'rb')) for x in material_names}

    # instrument parameter flags
    # !!! these come from the GUI tree view
    iflags = np.array(
        [0,
         1, 1,
         0,
         0, 0, 0,
         0, 0, 1, 1, 1, 1,
         0, 0, 0, 1, 1, 1],
        dtype=bool
    )
    instr.calibration_flags = iflags  # update instrument

    instr_calibrator = run_calibration(picks, instr, materials)
    instr.write_config('new-instrument-comp.yml')

    # %%
    """
    Now we just need to update the values in the GUI; the instrument class is
    updated already, can just grab its parameter dict
    The powder and laue parameters can be lifted from the corresp classes
    """
    for ical, cal_class in enumerate(instr_calibrator.calibrators):
        pnames = ['{:>24s}'.format(i[0]) for i in picks[ical]['refinements']]
        print("calibrator type: %s" % cal_class.calibrator_type)
        print("refined parameters:")
        for pname, param in zip(pnames, cal_class.params):
            print("\t%s = %.7e" % (pname, param))
