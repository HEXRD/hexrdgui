from __future__ import annotations

import copy
from typing import Any, TextIO

from PySide6.QtCore import QTimer

import h5py
import hdf5plugin
import numpy as np
import yaml

from hexrd import imageseries

import hexrdgui
from hexrdgui import state_compatibility
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_load_manager import ImageLoadManager

CONFIG_PREFIX = 'config'
CONFIG_YAML_PATH = f'{CONFIG_PREFIX}/yaml'


class H5StateLoader(yaml.SafeLoader):
    """
    A yaml.Loader implementation that allows !include <numpy_file_path>. This
    allows the loading of npy files into the YAML document from a HDF5 file. We
    also whitelist a new python types.
    """

    def __init__(
        self, *pargs: Any, h5_file: h5py.File | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*pargs, **kwargs)
        self.h5_file = h5_file

    def include(self, node: Any) -> Any:
        path = self.construct_scalar(node)
        assert self.h5_file is not None

        return self.h5_file[path][()]

    def hexrd_ui_constants_overlaytype(self, node: Any) -> Any:
        value = self.construct_sequence(node)

        return hexrdgui.constants.OverlayType(value[0])

    def python_tuple(self, node: Any) -> tuple[Any, ...]:
        value = self.construct_sequence(node)

        return tuple(value)


H5StateLoader.add_constructor('!include', H5StateLoader.include)
H5StateLoader.add_constructor(
    'tag:yaml.org,2002:python/object/apply:hexrdgui.constants.OverlayType',
    H5StateLoader.hexrd_ui_constants_overlaytype,
)
H5StateLoader.add_constructor(
    'tag:yaml.org,2002:python/tuple', H5StateLoader.python_tuple
)


def _dict_path_by_id(
    d: Any,
    value: int,
    path: tuple[str, ...] = (),
) -> tuple[str, ...] | None:
    if id(d) == value:
        return path
    elif isinstance(d, dict):
        for k, v in d.items():
            p = _dict_path_by_id(v, value, path + (k,))
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

    def __init__(
        self,
        stream: TextIO,
        h5_file: h5py.File | None = None,
        prefix: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(stream, **kwargs)

        self.h5_file = h5_file
        self.prefix = prefix

    def numpy_representer(self, data: np.ndarray) -> Any:
        path = _dict_path_by_id(self._dct, id(data))
        if path is None:
            raise ValueError('Unable to determine array path.')

        path_str = '/'.join(path)
        if self.prefix:
            path_str = f'{self.prefix}/{path_str}'

        assert self.h5_file is not None
        self.h5_file.create_dataset(path_str, data.shape, data.dtype, data=data)

        return self.represent_scalar('!include', path_str)

    # We need intercept the dict so we can lookup the paths to numpy types
    def represent(self, data: Any) -> Any:
        self._dct = data
        return super().represent(data)


H5StateDumper.add_representer(np.ndarray, H5StateDumper.numpy_representer)
H5StateDumper.add_representer(
    np.float64,
    H5StateDumper.numpy_representer,  # type: ignore[arg-type]
)


def _save_config(h5_file: h5py.File, config: dict[str, Any]) -> None:
    def _create_dumper(*arg: Any, **kwargs: Any) -> H5StateDumper:
        return H5StateDumper(  # type: ignore[misc]
            *arg, **kwargs, h5_file=h5_file, prefix=CONFIG_PREFIX
        )

    # Dump the YAML, this will write the numpy types to the H5 file
    config_yaml = yaml.dump(config, Dumper=_create_dumper)

    # Add the YAML as a string dataset
    h5_file.create_dataset(
        CONFIG_YAML_PATH, data=config_yaml, dtype=h5py.string_dtype()
    )


def _load_config(h5_file: h5py.File) -> dict[str, Any]:
    def _create_loader(*pargs: Any, **kwargs: Any) -> H5StateLoader:
        return H5StateLoader(*pargs, **kwargs, h5_file=h5_file)

    # First load extract the YAML string from the H5 file.
    config_yaml = h5_file[CONFIG_YAML_PATH][()]

    # Load it, which will cause the numpy type to be loaded as well.
    return yaml.load(config_yaml, Loader=_create_loader)  # type: ignore[arg-type]


def save(h5_file: h5py.File) -> None:
    """
    Save the state of the application in a HDF5 file
    """

    skip_list = [
        # We load the instrument config in a different way...
        'config_instrument',
        # We don't want to save the recent state files to the state file...
        'recent_state_files',
    ]

    state = HexrdConfig().state_to_persist()

    for entry in skip_list:
        if entry in state:
            del state[entry]

    # Save the state
    _save_config(h5_file, state)

    # Write out the materials
    HexrdConfig().save_materials_hdf5(h5_file, '/materials')

    # Write out the instrument
    HexrdConfig().save_instrument_config(h5_file)

    # Get any connected parts to save state...
    HexrdConfig().save_state.emit(h5_file)

    # Finally, write the imageseries...
    root = 'images'
    for det, ims in HexrdConfig().imageseries_dict.items():
        write_imageseries(h5_file, f'{root}/{det}', ims)


def load(h5_file: h5py.File) -> None:
    """
    Load application state from a HDF5 file
    """
    HexrdConfig().loading_state = True
    try:
        # First, load the materials
        HexrdConfig().load_materials(h5_file['/materials'])

        # Now, load the state
        state = _load_config(h5_file)

        # Don't set these defaults if they are missing.
        # Not sure why they are missing, but they cause issues if we
        # apply them.
        defaults_to_skip = [
            'config_instrument',
            'config_calibration',
            'config_indexing',
            'config_images',
        ]

        # Rename the state variables to the attribute names...
        renamed_state: dict[str, Any] = {}
        for name, default in HexrdConfig()._attributes_to_persist():
            old_name = HexrdConfig()._attribute_to_settings_key(name)
            if old_name in state:
                renamed_state[name] = state.pop(old_name)

            # Also set defaults if missing
            if name not in renamed_state and name not in defaults_to_skip:
                # If the attribute is not in the state, set it to the default
                # A deep copy is needed for mutable defaults
                renamed_state[name] = copy.deepcopy(default)

        HexrdConfig().load_from_state(renamed_state)

        # Load the instrument config...
        HexrdConfig().load_instrument_config(h5_file)

        # Get any connected parts to load state...
        HexrdConfig().load_state.emit(h5_file)

        # Finally, load the imageseries...
        load_imageseries_dict(h5_file)
    finally:
        HexrdConfig().loading_state = False

    # Record the location of the state file in case we save over it
    HexrdConfig().last_loaded_state_file = h5_file.filename

    def finalize() -> None:
        # Indicate that the state was loaded...
        HexrdConfig().state_loaded.emit()

        # Perform a deep rerender to make sure everything is updated...
        HexrdConfig().deep_rerender_needed.emit()

    # Allow some events to be processed, including loading the overlays,
    # before finalizing.
    QTimer.singleShot(0, finalize)


def load_imageseries_dict(h5_file: h5py.File) -> None:
    imsd = HexrdConfig().imageseries_dict
    imsd.clear()

    root = 'images'
    for det in list(h5_file[root]):
        imsd[det] = open_imageseries(h5_file, f'{root}/{det}')

    HexrdConfig().reset_unagg_imgs(new_imgs=True)

    ImageLoadManager().update_status = HexrdConfig().live_update
    ImageLoadManager().finish_processing_ims()


def update_if_needed(file_path: str) -> Any:
    return state_compatibility.update_if_needed(file_path)


# Compression used for image data in state files. blosc-zstd compresses our
# (often sparse) image data dramatically better than the previous gzip-1
# default, while staying lossless. h5py reads it back transparently as long as
# hdf5plugin is imported (which it is, above).
STATE_IMAGE_COMPRESSION = hdf5plugin.Blosc(
    cname='zstd', clevel=5, shuffle=hdf5plugin.Blosc.SHUFFLE
)

# Maximum nonzero fraction (sampled) for which the sparse fch5 format is used.
# Matches hexrd's frame-cache sparsity warning cutoff; above it, dense storage
# compresses as well or better.
FCH5_MAX_NZ_FRACTION = 0.1


def _write_as_fch5(ims: Any) -> bool:
    """Decide whether an imageseries should be stored as an fch5 frame cache.

    The frame cache zeroes out values at or below the threshold, so with a
    threshold of 0 it is only guaranteed lossless for unsigned integer data.
    Anything else (or data that is not actually sparse) keeps the dense hdf5
    layout.
    """
    if len(ims) == 0 or np.dtype(ims.dtype).kind != 'u':
        return False

    # Sample a few frames to estimate sparsity
    sample_idx = {0, len(ims) // 2, len(ims) - 1}
    fullness = max(np.count_nonzero(ims[i]) / ims[i].size for i in sample_idx)
    return fullness <= FCH5_MAX_NZ_FRACTION


def write_imageseries(h5_file: h5py.File, path: str, ims: Any) -> None:
    """Write an imageseries into the state file.

    Sparse unsigned-integer data is written as an fch5 frame cache (sparse
    storage, blosc-zstd compressed by hexrd). Everything else keeps the dense
    'hdf5' imageseries layout with a blosc-zstd filter (instead of its gzip-1
    default). Either way, it reads back via ``open_imageseries()``.
    """
    if _write_as_fch5(ims):
        # threshold=0 drops only exact zeros, which the sparse format
        # reconstructs implicitly, so this round-trips losslessly.
        imageseries.write(
            ims, h5_file, 'frame-cache', style='fch5', threshold=0, path=path
        )
    else:
        imageseries.write(
            ims, h5_file, 'hdf5', path=path, compression=STATE_IMAGE_COMPRESSION
        )


def open_imageseries(h5_file: h5py.File, path: str) -> Any:
    """Open an imageseries stored in a state file at the given path.

    Detects whether the group holds an fch5 frame cache (new state files) or
    a dense hdf5 imageseries (older state files, and the dense fallback) and
    opens it with the matching format. Either way the returned imageseries
    reads from the open ``h5_file``, so the file must stay open.
    """
    if 'HEXRD_FRAMECACHE_VERSION' in h5_file[path].attrs:
        return imageseries.open(h5_file, 'frame-cache', style='fch5', path=path)

    return imageseries.open(h5_file, 'hdf5', path=path, close_when_finished=False)
