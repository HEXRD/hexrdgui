from hexrd.utils.compatibility import h5py_read_string


def load_old_mask_file(self, h5py_group):
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
                for mask in masks.values():
                    # Load the numpy array from the hdf5 file
                    items[name].setdefault(key, []).append(mask[()])
