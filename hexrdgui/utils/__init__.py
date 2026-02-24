# Some general utilities that are used in multiple places

from __future__ import annotations

from contextlib import contextmanager
import copy
from enum import IntEnum
from functools import reduce
import math
import sys
from typing import Any, Callable, Generator, Sequence, TYPE_CHECKING, cast

from PySide6.QtCore import QEvent

import matplotlib.image
import matplotlib.transforms as mtransforms
import numpy as np

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QComboBox, QLayout

from hexrd import imageutil
from hexrd.imageseries.omega import OmegaImageSeries
from hexrd.instrument import HEDMInstrument
from hexrd.rotations import (
    angleAxisOfRotMat,
    angles_from_rmat_xyz,
    RotMatEuler,
    rotMatOfExpMap,
)
from hexrd.transforms.xfcapi import make_rmat_of_expmap
from hexrd.utils.decorators import memoize
from hexrd.utils.hkl import str_to_hkl
from hexrd.utils.panel_buffer import panel_buffer_as_2d_array
from types import TracebackType

if TYPE_CHECKING:
    from hexrd.material.crystallography import PlaneData


class SnipAlgorithmType(IntEnum):
    Fast_SNIP_1D = 0
    SNIP_1D = 1
    SNIP_2D = 2


def convert_tilt_convention(
    iconfig: dict[str, Any],
    old_convention: dict[str, Any] | None,
    new_convention: dict[str, Any] | None,
) -> None:
    """
    convert the tilt angles from an old convention to a new convention
    """
    if new_convention == old_convention:
        return

    det_keys = iconfig['detectors'].keys()
    if old_convention is not None:
        # First, convert these to the matrix invariants
        rme = RotMatEuler(np.zeros(3), **old_convention)
        for key in det_keys:
            tilts = iconfig['detectors'][key]['transform']['tilt']
            rme.angles = np.asarray(tilts)
            phi, n = angleAxisOfRotMat(rme.rmat)
            tilts[:] = (phi * n.flatten()).tolist()

        if new_convention is None:
            # We are done
            return

    # Update to the new mapping
    rme = RotMatEuler(np.zeros(3), **new_convention)
    for key in det_keys:
        tilts = iconfig['detectors'][key]['transform']['tilt']
        tilt = np.asarray(tilts)
        rme.rmat = make_rmat_of_expmap(tilt)
        # Use np.ndarray.tolist() to convert back to native python types
        tilts[:] = np.asarray(rme.angles).tolist()


def convert_angle_convention(
    angles: Any,
    old_convention: dict[str, Any] | None,
    new_convention: dict[str, Any] | None,
) -> Any:
    if old_convention is not None:
        # First, convert these to the matrix invariants
        rme = RotMatEuler(np.zeros(3), **old_convention)
        rme.angles = np.array(angles)
        phi, n = angleAxisOfRotMat(rme.rmat)
        angles = (phi * n.flatten()).tolist()

    if new_convention is None:
        # We are done
        return angles

    # Update to the new mapping
    rme = RotMatEuler(np.zeros(3), **new_convention)
    rme.rmat = make_rmat_of_expmap(np.array(angles))
    return np.array(rme.angles).tolist()


def coords2index(
    im: matplotlib.image.AxesImage,
    x: float,
    y: float,
) -> np.ndarray:
    """
    This function is modified from here:
    https://github.com/joferkington/mpldatacursor/blob/7dabc589ed02c35ac5d89de5931f91e0323aa795/mpldatacursor/pick_info.py#L28

    Converts data coordinates to index coordinates of the array.

    Parameters
    -----------
    im : An AxesImage instance
        The image artist to operate on
    x : number
        The x-coordinate in data coordinates.
    y : number
        The y-coordinate in data coordinates.

    Returns
    --------
    i, j : Index coordinates of the array associated with the image.
    """
    xmin, xmax, ymin, ymax = im.get_extent()
    if im.origin == 'upper':
        ymin, ymax = ymax, ymin
    data_extent = mtransforms.Bbox([[ymin, xmin], [ymax, xmax]])
    arr = im.get_array()
    assert arr is not None
    array_extent = mtransforms.Bbox([[0, 0], arr.shape[:2]])
    trans = mtransforms.BboxTransformFrom(data_extent) + mtransforms.BboxTransformTo(
        array_extent
    )

    return trans.transform_point([y, x]).astype(int)


def snip_width_pixels() -> int:

    from hexrdgui.hexrd_config import HexrdConfig

    pixel_size_tth = HexrdConfig().polar_pixel_size_tth
    snip_width_deg = HexrdConfig().polar_snip1d_width

    # Convert the snip width into pixels using pixel_size_tth
    # Always round up and return int
    return int(math.ceil(snip_width_deg / pixel_size_tth))


def run_snip1d(img: np.ndarray) -> np.ndarray:

    from hexrdgui.hexrd_config import HexrdConfig

    snip_width = snip_width_pixels()
    numiter = HexrdConfig().polar_snip1d_numiter
    algorithm = HexrdConfig().polar_snip1d_algorithm

    # Call the memoized function
    return _run_snip1d(img, snip_width, numiter, algorithm)


@memoize
def _run_snip1d(
    img: np.ndarray,
    snip_width: int,
    numiter: int,
    algorithm: SnipAlgorithmType,
) -> np.ndarray:
    if algorithm == SnipAlgorithmType.Fast_SNIP_1D:
        return imageutil.fast_snip1d(img, snip_width, numiter)
    elif algorithm == SnipAlgorithmType.SNIP_1D:
        return imageutil.snip1d(img, snip_width, numiter)
    elif algorithm == SnipAlgorithmType.SNIP_2D:
        return imageutil.snip2d(img, snip_width, numiter)

    # (else:)
    raise RuntimeError(f'Unrecognized polar_snip1d_algorithm {algorithm}')


def remove_none_distortions(iconfig: dict[str, Any]) -> None:
    # This modifies the iconfig in place to remove distortion
    # parameters that are set to None
    for det in iconfig['detectors'].values():
        function_name = det.get('distortion', {}).get('function_name', '')
        if function_name.lower() == 'none':
            del det['distortion']


class EventBlocker(QObject):
    """A context manager that can be used block a specific event"""

    def __init__(
        self,
        obj: QObject,
        event_type: QEvent.Type,
    ) -> None:
        super().__init__()
        self._obj = obj
        self._event_type = event_type

    def __enter__(self) -> None:
        self._obj.installEventFilter(self)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._obj.removeEventFilter(self)

    def eventFilter(  # type: ignore[override]
        self,
        obj: QObject,
        event: QEvent,
    ) -> bool:
        if event.type() == self._event_type:
            return True
        else:
            return super().eventFilter(obj, event)


def unique_name(
    items: Sequence[str],
    name: str,
    start: int = 1,
    delimiter: str = '_',
) -> str:
    value = start
    while name in items:
        prefix, delim, suffix = name.rpartition(delimiter)
        if not delim or not is_int(suffix):
            # We don't have a "<name><delim><num>" system yet. Start one.
            name += f'{delimiter}{value}'
        else:
            name = f'{prefix}{delim}{value}'
        value += 1

    return name


def wrap_with_callbacks(func: Callable[..., Any]) -> Callable[..., Any]:
    """Call callbacks before and/or after a member function

    If this decorator is used on a member function, and if there is also
    a member function defined on the object called
    '{before/after}_{function_name}_callback', that function will be
    called before/after the member function, with the same arguments
    that are given to the member function.
    """

    def callback(self: Any, when: str, *args: Any, **kwargs: Any) -> None:
        func_name = func.__name__
        callback_name = f'{when}_{func_name}_callback'
        f = self.__dict__.get(callback_name)
        if f is not None:
            f(*args, **kwargs)

    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        callback(self, 'before', *args, **kwargs)
        ret = func(self, *args, **kwargs)
        callback(self, 'after', *args, **kwargs)
        return ret

    return wrapper


def compose(*functions: Callable[..., Any]) -> Callable[..., Any]:
    # Combine a series of functions together.
    # Note that the functions are called from right to left.
    return reduce(lambda f, g: lambda x: f(g(x)), functions, lambda x: x)


class lazy_property:
    """Cache and always return the results of the first fetch"""

    def __init__(self, function: Callable[..., Any]) -> None:
        self.function = function
        self.name = function.__name__

    def __get__(self, obj: Any, type: Any = None) -> object:
        obj.__dict__[self.name] = self.function(obj)
        return obj.__dict__[self.name]


@contextmanager
def exclusions_off(plane_data: PlaneData) -> Generator[None, None, None]:
    prev = plane_data.exclusions
    plane_data.exclusions = None
    try:
        yield
    finally:
        plane_data.exclusions = prev


@contextmanager
def tth_max_off(plane_data: PlaneData) -> Generator[None, None, None]:
    prev = plane_data.tThMax
    plane_data.tThMax = None
    try:
        yield
    finally:
        plane_data.tThMax = prev


def has_nan(x: np.ndarray) -> bool:
    # Utility function to check if there are any NaNs in x
    return np.isnan(np.min(x))


def instr_to_internal_dict(
    instr: HEDMInstrument,
    calibration_dict: dict[str, Any] | None = None,
    convert_tilts: bool = True,
) -> dict[str, Any]:
    from hexrdgui.hexrd_config import HexrdConfig

    # Convert an HEDMInstrument object into an internal dict we can
    # use for HexrdConfig.

    if calibration_dict is None:
        calibration_dict = {}

    # First, in case the panel buffers are numpy arrays, save the panel
    # buffers for each detector and remove them. This is so we won't
    # get a warning when hexrd clobbers the numpy arrays.
    panel_buffers = {}
    for key, panel in instr.detectors.items():
        panel_buffers[key] = panel.panel_buffer
        panel.panel_buffer = None

    try:
        config = instr.write_config(calibration_dict=calibration_dict)
    finally:
        # Restore the panel buffers
        for key, panel in instr.detectors.items():
            panel.panel_buffer = panel_buffers[key]

    # Set the panel buffers on the detectors
    for key, val in panel_buffers.items():
        config['detectors'][key]['buffer'] = val

    # Convert to the selected tilt convention
    eac = HexrdConfig().euler_angle_convention
    if convert_tilts and eac is not None:
        convert_tilt_convention(config, None, eac)

    return config


def is_int(s: str) -> bool:
    """Check if a string is an int"""
    try:
        int(s)
        return True
    except ValueError:
        return False


@contextmanager
def block_signals(*objects: QObject) -> Generator[None, None, None]:
    """Block signals of objects via a with block:

    with block_signals(object):
        ...

    """
    blocked = [QSignalBlocker(o) for o in objects]
    try:
        yield
    finally:
        blocked.clear()


def reversed_enumerate(
    sequence: Sequence[Any],
) -> zip[tuple[int, Any]]:
    return zip(
        reversed(range(len(sequence))),
        reversed(sequence),
    )


@contextmanager
def default_stdout_stderr() -> Generator[None, None, None]:
    # Ensure we are using default stdout and stderr in the context
    prev_stdout = sys.stdout
    prev_stderr = sys.stderr
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    try:
        yield
    finally:
        sys.stdout = prev_stdout
        sys.stderr = prev_stderr


def clear_layout(layout: QLayout) -> None:
    # Recursively removes all child layouts and deletes all child widgets
    while child := layout.takeAt(0):
        if isinstance(child, QLayout):
            clear_layout(child)
            child.deleteLater()
        else:
            w = child.widget()
            if w is not None:
                w.deleteLater()


def array_index_in_list(
    array: np.ndarray,
    array_list: list[np.ndarray],
) -> int:
    # Find the index of an array in a list of arrays
    for i, array2 in enumerate(array_list):
        if np.array_equal(array, array2):
            return i

    return -1


def unique_array_list(
    array_list: list[np.ndarray],
) -> list[np.ndarray]:
    # Return a list with unique arrays in it (duplicates removed)
    ret: list[np.ndarray] = []
    for array in array_list:
        if array_index_in_list(array, ret) == -1:
            # It is not in the list
            ret.append(array)

    return ret


def format_big_int(x: float, decimals: int = 2) -> str:
    labels = [
        (1e12, 'trillion'),
        (1e9, 'billion'),
        (1e6, 'million'),
        (1e3, 'thousand'),
    ]

    for divisor, label in labels:
        if x > divisor:
            return f'{round(x / divisor, decimals)} {label}'

    return f'{x}'


def format_memory_int(x: float, decimals: int = 2) -> str:
    labels = [
        (1e12, 'TB'),
        (1e9, 'GB'),
        (1e6, 'MB'),
        (1e3, 'KB'),
        (1e0, 'B'),
    ]

    for divisor, label in labels:
        if x > divisor:
            return f'{round(x / divisor, decimals)} {label}'

    return f'{x} B'


def apply_symmetric_constraint(x: np.ndarray) -> np.ndarray:
    # Copy values from upper triangle to lower triangle.
    # Only works for square matrices.
    for i in range(x.shape[0]):
        for j in range(i):
            x[i, j] = x[j, i]
    return x


def hkl_str_to_array(hkl: str) -> np.ndarray:
    # For instance: '1 -1 10' => np.array((1, -1, 10))
    return np.array(str_to_hkl(hkl))


def is_omega_imageseries(ims: object) -> bool:
    return isinstance(ims, OmegaImageSeries)


def set_combobox_enabled_items(
    cb: QComboBox,
    enable_list: np.ndarray | list[bool],
) -> None:
    if not isinstance(enable_list, np.ndarray):
        enable_list = np.array(enable_list)

    model = cast(QStandardItemModel, cb.model())
    for i, enable in enumerate(enable_list):
        item = model.item(i)
        item.setEnabled(bool(enable))

    # Now see if we need to change to a new index
    new_index = cb.currentIndex()
    if not model.item(new_index).isEnabled():
        # If it is not enabled, set the index to the first enabled entry
        enabled = np.nonzero(enable_list)[0]
        if enabled.size != 0:
            new_index = enabled[0]
        else:
            new_index = -1

    cb.setCurrentIndex(new_index)


def remove_duplicate_neighbors(points: np.ndarray) -> np.ndarray:
    # Remove any points from this 2D array that are duplicates with
    # their next neighbor.
    rolled = np.roll(points, -1, axis=0)
    delete_indices = np.all(np.isclose(rolled - points, 0), axis=1)
    return np.delete(points, delete_indices, axis=0)


def add_sample_points(points: np.ndarray, min_output_length: int) -> np.ndarray:
    """Add extra sample points to a 2D array of points

    This takes a 2D array of points and uses np.linspace() to add extra
    points in between each point and its nearest index neighbors (nearest
    neighbors by index, not by distance).

    The min_output_length is the minimum number of points for the output.
    The actual output will likely have more points than this.
    """
    if len(points) > min_output_length:
        # It's already greater than what was specified
        return points

    # Figure out how many repititions we should have with np.linspace
    num_reps = int(np.ceil(min_output_length / len(points)))

    # Roll the points over so we can pair each point with its neighbor
    rolled = np.roll(points, -1, axis=0)

    # Generate the extra points between each point and its neighbor
    # Adding endpoint=False significantly reduces our number of duplicates.
    output = np.linspace(points, rolled, num=num_reps, endpoint=False)

    # Transform back into the correct shape and return
    return output.T.reshape(2, -1).T


def convert_panel_buffer_to_2d_array(panel: Any) -> None:
    panel.panel_buffer = panel_buffer_as_2d_array(panel)


@contextmanager
def masks_applied_to_panel_buffers(
    instr: HEDMInstrument,
) -> Generator[None, None, None]:
    # Temporarily apply the masks to the panel buffers
    # This is useful, for instance, for auto point picking, where
    # we want the masked regions to be avoided.

    from hexrdgui.masking.mask_manager import MaskManager

    panel_buffers = {
        k: copy.deepcopy(v.panel_buffer) for k, v in instr.detectors.items()
    }

    try:
        MaskManager().apply_masks_to_panel_buffers(instr)
        yield
    finally:
        for det_key, panel in instr.detectors.items():
            panel.panel_buffer = panel_buffers[det_key]


def euler_angles_to_rmat(angles: Sequence[float]) -> np.ndarray:
    return rotMatOfExpMap(euler_angles_to_exp_map(angles))


def rmat_to_euler_angles(
    rmat: np.ndarray,
) -> np.ndarray | list[float]:
    from hexrdgui.hexrd_config import HexrdConfig

    # Convert from exp map parameters
    xyz = angles_from_rmat_xyz(rmat)
    old_convention = {
        'axes_order': 'xyz',
        'extrinsic': True,
    }
    new_convention = HexrdConfig().euler_angle_convention
    angles = convert_angle_convention(xyz, old_convention, new_convention)
    if new_convention is not None:
        angles = np.degrees(angles)

    return angles


def euler_angles_to_exp_map(
    angles: np.ndarray | Sequence[float],
) -> np.ndarray:
    from hexrdgui.hexrd_config import HexrdConfig

    # Convert to exp map parameters
    old_convention = HexrdConfig().euler_angle_convention
    if old_convention is not None:
        angles = np.radians(angles)
        new_convention = None
        angles = convert_angle_convention(angles, old_convention, new_convention)

    return np.asarray(angles)


def exp_map_to_euler_angles(
    angles: np.ndarray | Sequence[float],
) -> Any:
    from hexrdgui.hexrd_config import HexrdConfig

    # Convert from exp map parameters
    old_convention = None
    new_convention = HexrdConfig().euler_angle_convention
    angles = convert_angle_convention(angles, old_convention, new_convention)
    if new_convention is not None:
        angles = np.degrees(angles)

    return angles
