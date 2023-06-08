from hexrd.ui.constants import KNOWN_DETECTOR_NAMES


def guess_instrument_type(detectors):
    for instr_name, det_names in KNOWN_DETECTOR_NAMES.items():
        if any(x in det_names for x in detectors):
            return instr_name
