import hexrd.ui
from hexrd.ui.hexrd_config import HexrdConfig
import yaml
from pathlib import Path
import h5py
import numpy as np

CONFIG_PREFIX = "config"
CONFIG_YAML_PATH = str(Path(CONFIG_PREFIX) / "yaml")


class H5StateLoader(yaml.SafeLoader):
    """
    A yaml.Loader implementation that allows !include <numpy_file_path>. This
    allows the loading of npy files into the YAML document from a HDF5 file. We
    also whitelist a new python types.
    """

    def __init__(self, *pargs, h5_file=None, **kwargs):
        super().__init__(*pargs, **kwargs)
        self.h5_file = h5_file

    def include(self, node):
        path = self.construct_scalar(node)

        return self.h5_file[path][()]

    def hexrd_ui_constants_overlaytype(self, node):
        value = self.construct_sequence(node)

        return hexrd.ui.constants.OverlayType(value[0])

    def python_tuple(self, node):
        value = self.construct_sequence(node)

        return tuple(value)


H5StateLoader.add_constructor(u'!include', H5StateLoader.include)
H5StateLoader.add_constructor(
    u'tag:yaml.org,2002:python/object/apply:hexrd.ui.constants.OverlayType',
    H5StateLoader.hexrd_ui_constants_overlaytype)
H5StateLoader.add_constructor(
    u'tag:yaml.org,2002:python/tuple', H5StateLoader.python_tuple)


def _dict_path_by_id(d, value, path=()):
    if id(d) == value:
        return path
    elif isinstance(d, dict):
        for k, v in d.items():
            p = _dict_path_by_id(v, value, path + (k, ))
            if p is not None:
                return p
    elif isinstance(d, list):
        for i, v in enumerate(d):
            p = _dict_path_by_id(v, value, path + (str(i),))
            if p is not None:
                return p

    return None


class H5StateDumper(yaml.Dumper):
    """
    A yaml.Dumper implementation that will dump numpy types to a HDF5 file.
    The path generate from the values path in the YAML document is used as the
    path in the HDF5 file. For example:

    "foo":
        "bar": ndarray

    The ndarray would be saved in foo/bar.

    """
    def __init__(self, stream, h5_file=None, prefix=None, **kwargs):
        super().__init__(stream, **kwargs)

        self.h5_file = h5_file
        self.prefix = prefix

    def numpy_representer(self, data):
        path = _dict_path_by_id(self._dct, id(data))
        if path is None:
            raise ValueError("Unable to determine array path.")

        path = Path(*path)
        if self.prefix:
            path = Path(self.prefix) / path
        path = str(path)

        self.h5_file.create_dataset(path, data.shape, data.dtype, data=data)

        return self.represent_scalar('!include', path)

    # We need intercept the dict so we can lookup the paths to numpy types
    def represent(self, data):
        self._dct = data
        return super().represent(data)


H5StateDumper.add_representer(np.ndarray, H5StateDumper.numpy_representer)
H5StateDumper.add_representer(np.float64, H5StateDumper.numpy_representer)


def _save_config(h5_file, config):
    def _create_dumper(*arg, **kwargs):
        return H5StateDumper(*arg, **kwargs, h5_file=h5_file,
                             prefix=CONFIG_PREFIX)

    # Dump the YAML, this will write the numpy types to the H5 file
    config_yaml = yaml.dump(config, Dumper=_create_dumper)

    # Add the YAML as a string dataset
    h5_file.create_dataset(CONFIG_YAML_PATH, data=config_yaml,
                           dtype=h5py.string_dtype())


def _load_config(h5_file):
    def _create_loader(*pargs, **kwargs):
        return H5StateLoader(*pargs, **kwargs, h5_file=h5_file)

    # First load extract the YAML string from the H5 file.
    config_yaml = h5_file[CONFIG_YAML_PATH][()]

    # Load it, which will cause the numpy type to be loaded as well.
    return yaml.load(config_yaml, Loader=_create_loader)


def save(h5_file):
    """
    Save the state of the application in a HDF5 file
    """
    _save_config(h5_file, HexrdConfig().state_to_persist())


def load(h5_file):
    """
    Load application state from a HDF5 file
    """
    state = _load_config(h5_file)
    HexrdConfig().load_from_state(state)
