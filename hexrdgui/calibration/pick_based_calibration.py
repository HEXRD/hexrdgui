from hexrd.fitting.calibration import (
    InstrumentCalibrator,
    LaueCalibrator,
    PowderCalibrator,
)
from hexrdgui.utils.guess_instrument_type import guess_instrument_type


def make_calibrators_from_picks(instr, processed_picks, materials, img_dict):
    calibrators = []
    for pick_data in processed_picks:
        if pick_data['type'] == 'powder':
            kwargs = {
                'instr': instr,
                'material': materials[pick_data['material']],
                'img_dict': img_dict,
                'default_refinements': pick_data['default_refinements'],
                'tth_distortion': pick_data['tth_distortion'],
                'calibration_picks': pick_data['picks'],
            }
            calibrators.append(PowderCalibrator(**kwargs))

        elif pick_data['type'] == 'laue':
            # gpflags = [i[1] for i in pick_data['refinements']]
            kwargs = {
                'instr': instr,
                'material': materials[pick_data['material']],
                'grain_params': pick_data['options']['crystal_params'],
                'default_refinements': pick_data['default_refinements'],
                'min_energy': pick_data['options']['min_energy'],
                'max_energy': pick_data['options']['max_energy'],
                'calibration_picks': pick_data['picks'],
            }
            calibrators.append(LaueCalibrator(**kwargs))
    return calibrators


def create_instrument_calibrator(picks, instr, img_dict, materials):
    engineering_constraints = guess_instrument_type(instr.detectors)
    calibrators = make_calibrators_from_picks(instr, picks, materials,
                                              img_dict)

    return InstrumentCalibrator(
        *calibrators,
        engineering_constraints=engineering_constraints,
    )
