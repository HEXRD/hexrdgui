import h5py

VERSION_KEY = 'structureless_calibration_pick_points_version'
VERSION_NUMBER = 2


def load_picks_from_file(instr, selected_file):
    with h5py.File(selected_file, 'r') as rf:
        if VERSION_KEY not in rf.attrs:
            msg = (
                'This does not appear to be a structureless calibration '
                'pick points file'
            )
            raise InvalidFile(msg)

        if rf.attrs[VERSION_KEY] > VERSION_NUMBER:
            msg = (
                f'Version of file "{rf.attrs[VERSION_KEY]}" is newer than '
                f'the newest version of this reader "{VERSION_NUMBER}". '
                'Try updating HEXRDGUI!'
            )
            raise InvalidFile(msg)

        if rf.attrs[VERSION_KEY] == 1:
            picks = _load_picks_from_file_v1(rf)
            return _convert_v1_to_v2(instr, picks)
        else:
            # This should only be 2 at this point
            return _load_picks_from_file_v2(rf)


def save_picks_to_file(calibration_lines, selected_file):
    with h5py.File(selected_file, 'w') as wf:
        wf.attrs[VERSION_KEY] = VERSION_NUMBER
        for xray_source, lines in calibration_lines.items():
            beam_group = wf.create_group(xray_source)
            for i, det_lines in enumerate(lines):
                ring_group = beam_group.create_group(f'DS_ring_{i}')
                for det_key, data in det_lines.items():
                    ring_group[det_key] = data


def _load_picks_from_file_v1(rf: h5py.File):
    output = []
    i = 0
    while f'DS_ring_{i}' in rf:
        ring_group = rf[f'DS_ring_{i}']
        det_lines = {}
        for det_key, data in ring_group.items():
            det_lines[det_key] = data[()]

        output.append(det_lines)
        i += 1

    return output


def _convert_v1_to_v2(instr, picks) -> dict:
    if instr.has_multi_xrs:
        # Use the active beam
        xrs_name = instr.active_beam_name
    else:
        xrs_name = instr.beam_names[0]

    return {xrs_name: picks}


def _load_picks_from_file_v2(rf: h5py.File) -> dict:
    picks = {}
    for xrs_name in rf.keys():
        group = rf[xrs_name]
        output = []
        i = 0
        while f'DS_ring_{i}' in group:
            ring_group = group[f'DS_ring_{i}']
            det_lines = {}
            for det_key, data in ring_group.items():
                det_lines[det_key] = data[()]

            output.append(det_lines)
            i += 1

        picks[xrs_name] = output

    return picks


class InvalidFile(Exception):
    pass
