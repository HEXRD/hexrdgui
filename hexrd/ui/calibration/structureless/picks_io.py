import h5py

VERSION_KEY = 'structureless_calibration_pick_points_version'
VERSION_NUMBER = 1


def load_picks_from_file(selected_file):
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

        return _load_picks_from_file_v1(rf)


def save_picks_to_file(calibration_lines, selected_file):
    with h5py.File(selected_file, 'w') as wf:
        wf.attrs[VERSION_KEY] = VERSION_NUMBER
        for i, det_lines in enumerate(calibration_lines):
            ring_group = wf.create_group(f'DS_ring_{i}')
            for det_key, data in det_lines.items():
                ring_group[det_key] = data


def _load_picks_from_file_v1(rf):
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


class InvalidFile(Exception):
    pass
