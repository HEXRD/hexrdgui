# Some general utilities that are used in multiple places

from contextlib import contextmanager
import copy
from enum import IntEnum
from functools import reduce
import math
import sys

import matplotlib.transforms as mtransforms
import numpy as np

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtWidgets import QLayout

from hexrd import imageutil
from hexrd.imageseries.omega import OmegaImageSeries
from hexrd.rotations import angleAxisOfRotMat, RotMatEuler
from hexrd.transforms.xfcapi import makeRotMatOfExpMap
from hexrd.utils.decorators import memoize


class SnipAlgorithmType(IntEnum):
    Fast_SNIP_1D = 0
    SNIP_1D = 1
    SNIP_2D = 2


def convert_tilt_convention(iconfig, old_convention,
                            new_convention):
    """
    convert the tilt angles from an old convention to a new convention

    This should work for both configs with statuses and without
    """
    if new_convention == old_convention:
        return

    def _get_tilt_array(data):
        # This works for both a config with statuses, and without
        if isinstance(data, dict):
            return data.get('value')
        return data

    def _set_tilt_array(data, val):
        # This works for both a config with statuses, and without
        if isinstance(data, dict):
            data['value'] = val
        else:
            data.clear()
            data.extend(val)

    det_keys = iconfig['detectors'].keys()
    if old_convention is not None:
        # First, convert these to the matrix invariants
        rme = RotMatEuler(np.zeros(3), **old_convention)
        for key in det_keys:
            tilts = iconfig['detectors'][key]['transform']['tilt']
            rme.angles = np.array(_get_tilt_array(tilts))
            phi, n = angleAxisOfRotMat(rme.rmat)
            _set_tilt_array(tilts, (phi * n.flatten()).tolist())

        if new_convention is None:
            # We are done
            return

    # Update to the new mapping
    rme = RotMatEuler(np.zeros(3), **new_convention)
    for key in det_keys:
        tilts = iconfig['detectors'][key]['transform']['tilt']
        tilt = np.array(_get_tilt_array(tilts))
        rme.rmat = makeRotMatOfExpMap(tilt)
        # Use np.ndarray.tolist() to convert back to native python types
        _set_tilt_array(tilts, np.array(rme.angles).tolist())


def convert_angle_convention(angles, old_convention, new_convention):
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
    rme.rmat = makeRotMatOfExpMap(np.array(angles))
    return np.array(rme.angles).tolist()


def coords2index(im, x, y):
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
    array_extent = mtransforms.Bbox([[0, 0], im.get_array().shape[:2]])
    trans = (mtransforms.BboxTransformFrom(data_extent) +
             mtransforms.BboxTransformTo(array_extent))

    return trans.transform_point([y, x]).astype(int)


def snip_width_pixels():

    from hexrd.ui.hexrd_config import HexrdConfig

    pixel_size_tth = HexrdConfig().polar_pixel_size_tth
    snip_width_deg = HexrdConfig().polar_snip1d_width

    # Convert the snip width into pixels using pixel_size_tth
    # Always round up and return int
    return int(math.ceil(snip_width_deg / pixel_size_tth))


def run_snip1d(img):

    from hexrd.ui.hexrd_config import HexrdConfig

    snip_width = snip_width_pixels()
    numiter = HexrdConfig().polar_snip1d_numiter
    algorithm = HexrdConfig().polar_snip1d_algorithm

    # Call the memoized function
    return _run_snip1d(img, snip_width, numiter, algorithm)

@memoize
def _run_snip1d(img, snip_width, numiter, algorithm):
    if algorithm == SnipAlgorithmType.Fast_SNIP_1D:
        return imageutil.fast_snip1d(img, snip_width, numiter)
    elif algorithm == SnipAlgorithmType.SNIP_1D:
        return imageutil.snip1d(img, snip_width, numiter)
    elif algorithm == SnipAlgorithmType.SNIP_2D:
        return imageutil.snip2d(img, snip_width, numiter)

    # (else:)
    raise RuntimeError(f'Unrecognized polar_snip1d_algorithm {algorithm}')


def remove_none_distortions(iconfig):
    # This modifies the iconfig in place to remove distortion
    # parameters that are set to None
    # This also assumes an iconfig without statuses
    for det in iconfig['detectors'].values():
        function_name = det.get('distortion', {}).get('function_name', '')
        if isinstance(function_name, dict):
            function_name = function_name['value']
        if function_name.lower() == 'none':
            del det['distortion']


class EventBlocker(QObject):
    """ A context manager that can be used block a specific event """

    def __init__(self, obj, event_type):
        super().__init__()
        self._obj = obj
        self._event_type = event_type

    def __enter__(self):
        self._obj.installEventFilter(self)

    def __exit__(self, exc_type, exc_value, traceback):
        self._obj.removeEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == self._event_type:
            return True
        else:
            return super().eventFilter(obj, event)


def unique_name(items, name, start=1, delimiter='_'):
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


def wrap_with_callbacks(func):
    """Call callbacks before and/or after a member function

    If this decorator is used on a member function, and if there is also
    a member function defined on the object called
    '{before/after}_{function_name}_callback', that function will be
    called before/after the member function, with the same arguments
    that are given to the member function.
    """
    def callback(self, when, *args, **kwargs):
        func_name = func.__name__
        callback_name = f'{when}_{func_name}_callback'
        f = self.__dict__.get(callback_name)
        if f is not None:
            f(*args, **kwargs)

    def wrapper(self, *args, **kwargs):
        callback(self, 'before', *args, **kwargs)
        ret = func(self, *args, **kwargs)
        callback(self, 'after', *args, **kwargs)
        return ret

    return wrapper


def compose(*functions):
    # Combine a series of functions together.
    # Note that the functions are called from right to left.
    return reduce(lambda f, g: lambda x: f(g(x)), functions, lambda x: x)


class lazy_property:
    """Cache and always return the results of the first fetch"""
    def __init__(self, function):
        self.function = function
        self.name = function.__name__

    def __get__(self, obj, type=None) -> object:
        obj.__dict__[self.name] = self.function(obj)
        return obj.__dict__[self.name]


@contextmanager
def exclusions_off(plane_data):
    prev = plane_data.exclusions
    plane_data.exclusions = None
    try:
        yield
    finally:
        plane_data.exclusions = prev


@contextmanager
def tth_max_off(plane_data):
    prev = plane_data.tThMax
    plane_data.tThMax = None
    try:
        yield
    finally:
        plane_data.tThMax = prev


def has_nan(x):
    # Utility function to check if there are any NaNs in x
    return np.isnan(np.min(x))


def instr_to_internal_dict(instr, calibration_dict=None, convert_tilts=True):
    from hexrd.ui.hexrd_config import HexrdConfig

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


def is_int(s):
    """Check if a string is an int"""
    try:
        int(s)
        return True
    except ValueError:
        return False


@contextmanager
def block_signals(*objects):
    """Block signals of objects via a with block:

    with block_signals(object):
        ...

    """
    blocked = [QSignalBlocker(o) for o in objects]
    try:
        yield
    finally:
        blocked.clear()


def reversed_enumerate(sequence):
    return zip(
        reversed(range(len(sequence))),
        reversed(sequence),
    )


@contextmanager
def default_stdout_stderr():
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


def clear_layout(layout):
    # Recursively removes all child layouts and deletes all child widgets
    while child := layout.takeAt(0):
        if isinstance(child, QLayout):
            clear_layout(child)
            child.deleteLater()
        else:
            child.widget().deleteLater()


def array_index_in_list(array, array_list):
    # Find the index of an array in a list of arrays
    for i, array2 in enumerate(array_list):
        if np.array_equal(array, array2):
            return i

    return -1


def unique_array_list(array_list):
    # Return a list with unique arrays in it (duplicates removed)
    ret = []
    for array in array_list:
        if array_index_in_list(array, ret) == -1:
            # It is not in the list
            ret.append(array)

    return ret


def format_big_int(x, decimals=2):
    labels = [
        (1e12, 'trillion'),
        (1e9,  'billion'),
        (1e6,  'million'),
        (1e3,  'thousand'),
    ]

    for divisor, label in labels:
        if x > divisor:
            return f'{round(x / divisor, decimals)} {label}'

    return f'{x}'


def format_memory_int(x, decimals=2):
    labels = [
        (1e12, 'TB'),
        (1e9,  'GB'),
        (1e6,  'MB'),
        (1e3,  'KB'),
        (1e0,  'B'),
    ]

    for divisor, label in labels:
        if x > divisor:
            return f'{round(x / divisor, decimals)} {label}'

    return f'{x} B'


def apply_symmetric_constraint(x):
    # Copy values from upper triangle to lower triangle.
    # Only works for square matrices.
    for i in range(x.shape[0]):
        for j in range(i):
            x[i, j] = x[j, i]
    return x


def hkl_str_to_array(hkl):
    # For instance: '1 -1 10' => np.array((1, -1, 10))
    return np.array(list(map(int, hkl.split())))


def is_omega_imageseries(ims):
    return isinstance(ims, OmegaImageSeries)


def set_combobox_enabled_items(cb, enable_list):
    if not isinstance(enable_list, np.ndarray):
        enable_list = np.array(enable_list)

    model = cb.model()
    for i, enable in enumerate(enable_list):
        item = model.item(i)
        item.setEnabled(enable)

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


def add_sample_points(points, min_output_length):
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
    output = np.linspace(points, rolled, num=num_reps)

    # Transform back into the correct shape and return
    return output.T.reshape(2, -1).T


def convert_panel_buffer_to_2d_array(panel):
    # Take whatever the panel buffer is and convert it to a 2D array
    if panel.panel_buffer is None:
        # Just make a panel buffer with all True values
        panel.panel_buffer = np.ones(panel.shape, dtype=bool)
    elif panel.panel_buffer.shape == (2,):
        # The two floats are specifying the borders in mm for x and y.
        # Convert to pixel borders. Swap x and y so we have i, j in pixels.
        borders = np.round([
            panel.panel_buffer[1] / panel.pixel_size_row,
            panel.panel_buffer[0] / panel.pixel_size_col,
        ]).astype(int)

        # Convert to array
        panel_buffer = np.zeros(panel.shape, dtype=bool)

        # We can't do `-borders[i]` since that doesn't work for 0,
        # so we must do `panel.shape[i] - borders[i]` instead.
        panel_buffer[borders[0]:panel.shape[0] - borders[0],
                     borders[1]:panel.shape[1] - borders[1]] = True
        panel.panel_buffer = panel_buffer
    elif panel.panel_buffer.ndim != 2:
        raise NotImplementedError(panel.panel_buffer.ndim)


@contextmanager
def masks_applied_to_panel_buffers(instr):
    # Temporarily apply the masks to the panel buffers
    # This is useful, for instance, for auto point picking, where
    # we want the masked regions to be avoided.

    from hexrd.ui.hexrd_config import HexrdConfig

    panel_buffers = {k: copy.deepcopy(v.panel_buffer)
                     for k, v in instr.detectors.items()}

    try:
        HexrdConfig().apply_masks_to_panel_buffers(instr)
        yield
    finally:
        for det_key, panel in instr.detectors.items():
            panel.panel_buffer = panel_buffers[det_key]
