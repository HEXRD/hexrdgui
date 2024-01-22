from hexrd.instrument import unwrap_h5_to_dict
from hexrd.utils.compatibility import h5py_read_string

from hexrdgui.masking.constants import CURRENT_MASK_VERSION


def convert_masks_v1_to_v2(h5py_group):
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
                    'data': {},
                })
                for i, mask in enumerate(masks.values()):
                    # Load the numpy array from the hdf5 file
                    items[name]['data'].setdefault(key, {})[i] = mask[()]
    return items


def load_masks(h5py_group):
    version = h5py_group.attrs.get("_version", 1)
    if version != CURRENT_MASK_VERSION:
        return CONVERSION_DICT[(version, CURRENT_MASK_VERSION)](h5py_group)

    d = {}
    unwrap_h5_to_dict(h5py_group, d)
    return d


CONVERSION_DICT = {
    (1, 2): convert_masks_v1_to_v2,
}
