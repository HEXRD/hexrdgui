CURRENT_DICT_VERSION = 2


def material_name(overlay_dict):
    version = overlay_dict.get('_version', 1)
    if version == 1:
        key = 'material'
    else:
        key = 'material_name'

    return overlay_dict.get(key)


def to_dict(overlay):
    d = overlay.to_dict()
    # Keep track of a version so we can convert between formats properly
    d['_version'] = CURRENT_DICT_VERSION
    return d


def from_dict(cls, d):
    version = d.pop('_version', 1)

    if 'eta_period' in d:
        # This is now always taken from HexrdConfig() and is not a setting
        del d['eta_period']

    if d.get('tth_distortion_type') == 'PinholeDistortion':
        # This was renamed to `RyggPinholeDistortion` in 93c5a50b
        d['tth_distortion_type'] = 'RyggPinholeDistortion'

    if version != CURRENT_DICT_VERSION:
        # Convert to the current version
        type_str = cls.type.value
        d = CONVERSION_DICT[(version, CURRENT_DICT_VERSION)](d, type_str)

    return cls(**d)


def convert_dict_v1_to_v2(d, type_str):
    func_name = f'{type_str}_dict_v1_to_v2'

    if func_name not in globals():
        raise NotImplementedError(f'Unknown type: {type_str}')

    return globals()[func_name](d)


def base_dict_v1_to_v2(d):
    ret = {}

    # Material is required
    ret['material_name'] = d['material']

    if 'refinements' in d:
        # We now only set the values, not the labels
        ret['refinements'] = [x[1] for x in d['refinements']]

    root_to_get = [
        'style',
        'visible',
    ]
    for name in root_to_get:
        if name in d:
            ret[name] = d[name]

    return ret


def powder_dict_v1_to_v2(d):
    ret = base_dict_v1_to_v2(d)

    options = d.get('options', {})
    options_to_get = [
        'tvec',
        'eta_steps',
        'eta_period',
    ]
    _set_if_present(ret, options, options_to_get)

    return ret


def laue_dict_v1_to_v2(d):
    ret = base_dict_v1_to_v2(d)

    options = d.get('options', {})
    options_to_get = [
        'crystal_params',
        'sample_rmat',
        'min_energy',
        'max_energy',
        'tth_width',
        'eta_width',
        'eta_period',
        'width_shape',
    ]
    _set_if_present(ret, options, options_to_get)
    return ret


def rotation_series_dict_v1_to_v2(d):
    ret = base_dict_v1_to_v2(d)

    options = d.get('options', {})
    options_to_get = [
        'crystal_params',
        'eta_ranges',
        'ome_ranges',
        'ome_period',
        'eta_period',
        'aggregated',
        'ome_width',
        'tth_width',
        'eta_width',
    ]
    _set_if_present(ret, options, options_to_get)

    internal = d.get('internal', {})
    internal_to_get = [
        'sync_ome_period',
        'sync_ome_ranges',
    ]
    _set_if_present(ret, internal, internal_to_get)
    return ret


def _set_if_present(ret, d, name_list):
    for name in name_list:
        if name in d:
            ret[name] = d[name]


CONVERSION_DICT = {
    (1, 2): convert_dict_v1_to_v2,
}
