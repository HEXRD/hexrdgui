from hexrd.fitting.calibration import (
    InstrumentCalibrator,
    LaueCalibrator,
    PowderCalibrator,
)
from hexrdgui.calibration.calibration_dialog import (
    guess_engineering_constraints,
)
from hexrdgui.hexrd_config import HexrdConfig


def make_calibrators_from_picks(instr, processed_picks, materials, img_dict,
                                euler_convention):
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
                'xray_source': pick_data['xray_source'],
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
                'euler_convention': euler_convention,
                'xray_source': pick_data['xray_source'],
            }
            calibrators.append(LaueCalibrator(**kwargs))
    return calibrators


def create_instrument_calibrator(picks, instr, img_dict, materials):
    euler_convention = HexrdConfig().euler_angle_convention
    engineering_constraints = guess_engineering_constraints(instr)
    calibrators = make_calibrators_from_picks(instr, picks, materials,
                                              img_dict, euler_convention)

    return InstrumentCalibrator(
        *calibrators,
        engineering_constraints=engineering_constraints,
        euler_convention=euler_convention,
    )
