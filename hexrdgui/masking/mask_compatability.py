from hexrd.utils.compatibility import h5py_read_string


def load_masks_v1_to_v2(h5py_group):
    if h5py_group.get("_version") == 2:
        return h5py_group.items()
    else:
        # This is a file using the old format
        items = {}
        visible = list(h5py_read_string(h5py_group['_visible']))
        for key, data in h5py_group.items():
            if key == '_visible':
                continue

            if key == 'threshold':
                values = data['values'][()].tolist()
                items['threshold'] = {
                    'min_val': values[0],
                    'max_val': values[1],
                    'name': 'threshold',
                    'mtype': 'threshold',
                    'visible': 'threshold' in visible,
                    'border': False,
                }
            else:
                for name, masks in data.items():
                    items.setdefault(name, {
                        'name': name,
                        'mtype': 'unknown',
                        'visible': name in visible,
                        'border': False,
                    })
                    for i, mask in enumerate(masks.values()):
                        # Load the numpy array from the hdf5 file
                        items[name].setdefault(key, {})[i] = mask[()]
        return [(k, v) for k, v in items.items()]
