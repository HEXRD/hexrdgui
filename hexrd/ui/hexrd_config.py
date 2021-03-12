import copy
import os

from PySide2.QtCore import Signal, QCoreApplication, QObject, QSettings

import numpy as np
import yaml

import hexrd.imageseries.save
from hexrd.rotations import RotMatEuler
from hexrd.config.loader import NumPyIncludeLoader
from hexrd.config.dumper import NumPyIncludeDumper
from hexrd.material import load_materials_hdf5, save_materials_hdf5, Material
from hexrd.valunits import valWUnit

from hexrd.ui import constants
from hexrd.ui import overlays
from hexrd.ui import resource_loader
from hexrd.ui import utils

import hexrd.ui.resources.calibration
import hexrd.ui.resources.indexing
import hexrd.ui.resources.materials


# This metaclass must inherit from `type(QObject)` for classes that use
# it to inherit from QObject.
class Singleton(type(QObject)):

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args,
                                                                 **kwargs)
        return cls._instances[cls]


# This is a singleton class that contains the configuration
class HexrdConfig(QObject, metaclass=Singleton):
    """The central configuration class for the program

    This class contains properties where possible, and it uses the
    following syntax for declaring them:

    name = property(_name, _set_name)

    This is done so that _set_name() may be connected to in Qt's signal
    and slot syntax.
    """

    """Emitted when new plane data is generated for the active material"""
    new_plane_data = Signal()

    """Emitted when overlay configuration has changed"""
    overlay_config_changed = Signal()

    """Emitted when beam vector has changed"""
    beam_vector_changed = Signal()

    """Emitted when the option to show the saturation level is changed"""
    show_saturation_level_changed = Signal()

    """Emitted when the option to tab images is changed"""
    tab_images_changed = Signal()

    """Emitted when a detector's transform is modified"""
    detector_transform_modified = Signal(str)

    """Emitted when detector borders need to be re-rendered"""
    rerender_detector_borders = Signal()

    """Emitted when wppf needs to be re-rendered"""
    rerender_wppf = Signal()

    """Emitted for any config changes EXCEPT detector transform changes

    Indicates that the image needs to be re-drawn from scratch.

    Note that this does not do anything if "Show Live Updates" is off.
    """
    rerender_needed = Signal()

    """Emitted for any changes that need a re-render from scratch

    This causes all canvases to be cleared and re-rendered.
    """
    deep_rerender_needed = Signal()

    """Emitted when detectors have been added or removed"""
    detectors_changed = Signal()

    """Emitted when an instrument config has been loaded

    Warning: this will cause cartesian and polar parameters to be
    automatically regenerated, which are time consuming functions.
    """
    instrument_config_loaded = Signal()

    """Convenience signal to update the main window's status bar

    Arguments are: message (str)

    """
    update_status_bar = Signal(str)

    """Emitted when the load_panel_state has been cleared"""
    load_panel_state_reset = Signal()

    """Emitted when the workflow has been changed"""
    workflow_changed = Signal()

    """Emitted when the Euler angle convention changes"""
    euler_angle_convention_changed = Signal()

    """Emitted when the threshold mask status changes via image mode"""
    mode_threshold_mask_changed = Signal(bool)

    """Emitted when the threshold mask status changes via mask manager"""
    mgr_threshold_mask_changed = Signal(bool)

    """Emitted when the active material is changed to a different material"""
    active_material_changed = Signal()

    """Emitted when the materials panel should update"""
    active_material_modified = Signal()

    """Emitted when a material is renamed"""
    material_renamed = Signal()

    """Emitted when a material is removed"""
    material_removed = Signal()

    """Emitted when a new raw mask has been created"""
    raw_masks_changed = Signal()

    """Emitted when a new polar mask has been created"""
    polar_masks_changed = Signal()

    """Emitted when point picked calibration is complete"""
    calibration_complete = Signal()

    def __init__(self):
        # Should this have a parent?
        super(HexrdConfig, self).__init__(None)
        self.config = {}
        self.default_config = {}
        self.gui_yaml_dict = None
        self.cached_gui_yaml_dicts = {}
        self.calibration_flags_order = {}
        self.working_dir = None
        self.images_dir = None
        self.imageseries_dict = {}
        self.current_imageseries_idx = 0
        self.hdf5_path = []
        self.live_update = True
        self._show_saturation_level = False
        self._tab_images = False
        self.previous_active_material = None
        self.collapsed_state = []
        self.load_panel_state = {}
        self.polar_masks = {}
        self.polar_masks_line_data = {}
        self.raw_masks = {}
        self.raw_masks_line_data = {}
        self.visible_masks = []
        self.backup_tth_maxes = {}
        self.overlays = []
        self.wppf_data = None
        self.workflow = None
        self.last_azimuthal_integral_data = None
        self._threshold_data = {}
        self.stack_state = {}

        default_conv = constants.DEFAULT_EULER_ANGLE_CONVENTION
        self.set_euler_angle_convention(default_conv, convert_config=False)

        # Load default configuration settings
        self.load_default_config()

        self.config['materials'] = copy.deepcopy(
            self.default_config['materials'])

        if '--ignore-settings' not in QCoreApplication.arguments():
            self.load_settings()

        self.set_defaults_if_missing()

        # Remove any 'None' distortion dicts from the detectors
        utils.remove_none_distortions(self.config['instrument'])

        # Add the statuses to the config
        self.create_internal_config(self.config['instrument'])

        # Save a backup of the previous config for later
        self.backup_instrument_config()

        # Load the GUI to yaml maps
        self.load_gui_yaml_dict()

        # Load calibration flag order
        self.load_calibration_flags_order()

        # Load the default materials
        self.load_default_materials()

        # Re-load the previous active material if available
        mat = self.previous_active_material
        if mat is not None and mat in self.materials.keys():
            self.active_material = mat

        self.update_visible_material_energies()

    def save_settings(self):
        settings = QSettings()
        settings.setValue('config_instrument', self.config['instrument'])
        settings.setValue('config_calibration', self.config['calibration'])
        settings.setValue('config_indexing', self.indexing_config)
        settings.setValue('config_image', self.config['image'])
        settings.setValue('images_dir', self.images_dir)
        settings.setValue('working_dir', self.working_dir)
        settings.setValue('hdf5_path', self.hdf5_path)
        settings.setValue('live_update', self.live_update)
        settings.setValue('euler_angle_convention',
                          self.euler_angle_convention)
        settings.setValue('active_material', self.active_material_name)
        settings.setValue('collapsed_state', self.collapsed_state)
        settings.setValue('load_panel_state', self.load_panel_state)
        settings.setValue('image_stack_state', self.stack_state)

        # Clear the overlay data and save the overlays as well
        HexrdConfig().clear_overlay_data()
        settings.setValue('overlays', self.overlays)
        settings.setValue('workflow', self.workflow)

    def set_workflow(self, workflow):
        if workflow == self.workflow:
            return

        self.workflow = workflow
        self.workflow_changed.emit()

    def load_settings(self):
        settings = QSettings()
        self.config['instrument'] = settings.value('config_instrument', None)
        self.config['calibration'] = settings.value('config_calibration', None)
        self.config['indexing'] = settings.value('config_indexing', None)
        self.config['image'] = settings.value('config_image', None)
        self.images_dir = settings.value('images_dir', None)
        self.working_dir = settings.value('working_dir', None)
        self.hdf5_path = settings.value('hdf5_path', None)
        # All QSettings come back as strings.
        self.live_update = settings.value('live_update', 'true') == 'true'

        default_convention = constants.DEFAULT_EULER_ANGLE_CONVENTION
        conv = settings.value('euler_angle_convention', default_convention)
        if isinstance(conv, tuple):
            # Convert to our new method of storing it
            conv = {'axes_order': conv[0], 'extrinsic': conv[1]}

        self.set_euler_angle_convention(conv, convert_config=False)

        self.previous_active_material = settings.value('active_material', None)
        self.collapsed_state = settings.value('collapsed_state', [])
        self.load_panel_state = settings.value('load_panel_state', {})
        self.stack_state = settings.value('image_stack_state', {})

        self.overlays = settings.value('overlays', [])
        self.overlays = self.overlays if self.overlays is not None else []

        # For backward compatibility:
        for overlay in self.overlays:
            overlay['type'] = constants.OverlayType(overlay['type'])

        self.workflow = settings.value('workflow', None)

    def emit_update_status_bar(self, msg):
        """Convenience signal to update the main window's status bar"""
        self.update_status_bar.emit(msg)

    @property
    def indexing_config(self):
        return self.config['indexing']

    # This is here for backward compatibility
    @property
    def instrument_config(self):
        return self.filter_instrument_config(
            self.config['instrument'])

    @property
    def internal_instrument_config(self):
        return self.config['instrument']

    def backup_instrument_config(self):
        self.instrument_config_backup = copy.deepcopy(
            self.config['instrument'])
        self.instrument_config_backup_eac = copy.deepcopy(
            self.euler_angle_convention)

    def restore_instrument_config_backup(self):
        old_detectors = self.detector_names
        self.config['instrument'] = copy.deepcopy(
            self.instrument_config_backup)

        old_eac = self.instrument_config_backup_eac
        new_eac = self.euler_angle_convention
        if old_eac != new_eac:
            # Convert it to whatever convention we are using
            utils.convert_tilt_convention(self.config['instrument'], old_eac,
                                          new_eac)

        # Because it is a time-consuming process, don't emit
        # instrument_config_loaded, which will re-generate Cartesian and
        # polar parameters. We'll just leave them at whatever they were
        # last set to (either auto-generated or user set).

        new_detectors = self.detector_names
        if old_detectors != new_detectors:
            self.detectors_changed.emit()
        else:
            # Still need a deep rerender
            self.deep_rerender_needed.emit()

        self.update_visible_material_energies()
        self.update_active_material_energy()

    def set_images_dir(self, images_dir):
        self.images_dir = images_dir

    def load_gui_yaml_dict(self):
        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'yaml_to_gui.yml')
        self.gui_yaml_dict = yaml.load(text, Loader=yaml.FullLoader)

    def load_calibration_flags_order(self):
        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'calibration_flags_order.yml')
        self.calibration_flags_order = yaml.load(text, Loader=yaml.FullLoader)

    def load_default_config(self):
        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'default_instrument_config.yml')
        self.default_config['instrument'] = yaml.load(text,
                                                      Loader=yaml.FullLoader)

        text = resource_loader.load_resource(hexrd.ui.resources.indexing,
                                             'default_indexing_config.yml')
        self.default_config['indexing'] = yaml.load(text,
                                                    Loader=yaml.FullLoader)

        yml = resource_loader.load_resource(hexrd.ui.resources.materials,
                                            'materials_panel_defaults.yml')
        self.default_config['materials'] = yaml.load(yml,
                                                     Loader=yaml.FullLoader)

        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'default_image_config.yml')
        self.default_config['image'] = yaml.load(text, Loader=yaml.FullLoader)

        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'default_calibration_config.yml')
        self.default_config['calibration'] = yaml.load(text,
                                                       Loader=yaml.FullLoader)

    def set_defaults_if_missing(self):
        # Find missing required keys and set defaults for them.
        to_do_keys = ['indexing', 'instrument', 'calibration', 'image']
        for key in to_do_keys:
            if self.config.get(key) is None:
                self.config[key] = copy.deepcopy(self.default_config[key])
                continue

            self._recursive_set_defaults(self.config[key],
                                         self.default_config[key])

        self.set_detector_defaults_if_missing()

    def set_detector_defaults_if_missing(self):
        # Find missing keys under detectors and set defaults for them
        default = self.default_detector
        for name in self.detector_names:
            self._recursive_set_defaults(self.detector(name), default)

    def _recursive_set_defaults(self, current, default):
        for key in default.keys():
            current.setdefault(key, copy.deepcopy(default[key]))

            if key == 'detectors':
                # Don't copy the default detectors into the current ones
                continue

            if isinstance(default[key], dict):
                self._recursive_set_defaults(current[key], default[key])

    def image(self, name, idx):
        return self.imageseries(name)[idx]

    def imageseries(self, name):
        return self.imageseries_dict.get(name)

    def has_images(self):
        return len(self.imageseries_dict) != 0

    def current_images_dict(self):
        idx = self.current_imageseries_idx
        ret = {}
        for key in self.imageseries_dict.keys():
            ret[key] = self.image(key, idx)

        return ret

    def save_imageseries(self, ims, name, write_file, selected_format,
                         **kwargs):
        hexrd.imageseries.save.write(ims, write_file, selected_format,
                                     **kwargs)

    def clear_images(self, initial_load=False):
        self.imageseries_dict.clear()
        if self.load_panel_state is not None and not initial_load:
            self.load_panel_state.clear()
            self.load_panel_state_reset.emit()

    def load_instrument_config(self, yml_file):
        old_detectors = self.detector_names
        with open(yml_file, 'r') as f:
            self.config['instrument'] = yaml.load(f, Loader=NumPyIncludeLoader)

        eac = self.euler_angle_convention
        if eac is not None:
            # Convert it to whatever convention we are using
            utils.convert_tilt_convention(self.config['instrument'], None, eac)

        # Set any required keys that might be missing to prevent key errors
        self.set_defaults_if_missing()

        # Remove any 'None' distortion dicts from the detectors
        utils.remove_none_distortions(self.config['instrument'])

        self.create_internal_config(self.config['instrument'])

        # Create a backup
        self.backup_instrument_config()

        # Temporarily turn off overlays. They will be updated later.
        self.clear_overlay_data()
        prev = self.show_overlays
        self.config['materials']['show_overlays'] = False
        self.update_visible_material_energies()
        self.update_active_material_energy()
        self.config['materials']['show_overlays'] = prev

        self.instrument_config_loaded.emit()

        new_detectors = self.detector_names
        if old_detectors != new_detectors:
            self.detectors_changed.emit()
        else:
            # Still need a deep rerender
            self.deep_rerender_needed.emit()

        return self.config['instrument']

    def save_instrument_config(self, output_file):
        default = self.filter_instrument_config(self.config['instrument'])
        eac = self.euler_angle_convention
        if eac is not None:
            # Convert it to None convention before saving
            utils.convert_tilt_convention(default, eac, None)

        with open(output_file, 'w') as f:
            yaml.dump(default, f, Dumper=NumPyIncludeDumper)

    def load_materials(self, f):
        beam_energy = valWUnit('beam', 'energy', self.beam_energy, 'keV')
        self.materials = load_materials_hdf5(f, kev=beam_energy)

    def save_materials(self, f):
        save_materials_hdf5(f, self.materials)

    def import_material(self, f):
        beam_energy = valWUnit('beam', 'energy', self.beam_energy, 'keV')
        base_name = os.path.splitext(os.path.basename(f))[0]

        # Make sure we have a unique name
        ind = 1
        name = base_name
        while name in self.materials:
            name = base_name + f'_{ind}'
            ind += 1

        material = Material(name, f, kev=beam_energy)
        self.add_material(name, material)

        return name

    def set_live_update(self, status):
        self.live_update = status

    def create_internal_config(self, cur_config):
        if not self.has_status(cur_config):
            self.add_status(cur_config)

    def filter_instrument_config(self, cur_config):
        # Filters the refined status values out of the
        # instrument config tree
        default = {}
        default['instrument'] = copy.deepcopy(cur_config)
        if self.has_status(default['instrument']):
            self.remove_status(default['instrument'])
            return default['instrument']
        return cur_config

    def update_collapsed_state(self, item):
        if self.collapsed_state is None:
            self.collapsed_state = []

        if item not in self.collapsed_state:
            self.collapsed_state.append(item)
        else:
            self.collapsed_state.remove(item)

    def has_status(self, config):
        if isinstance(config, dict):
            if 'status' in config.keys():
                return True

            for v in config.values():
                if self.has_status(v):
                    return True

        return False

    def add_status(self, current):
        for key, value in current.items():
            if isinstance(value, dict):
                self.add_status(value)
            else:
                if isinstance(value, list):
                    stat_default = [0] * len(value)
                else:
                    stat_default = 0
                current[key] = {'status': (stat_default), 'value': value}

    def remove_status(self, current, prev=None, parent=None):
        for key, value in current.items():
            if isinstance(value, dict):
                if 'status' in value.keys():
                    current[key] = value['value']
                else:
                    self.remove_status(value, current, key)

    def get_statuses_instrument_format(self):
        """This gets statuses in the hexrd instrument format"""
        statuses = []

        iflags_order = self.calibration_flags_order['instrument']
        dflags_order = self.calibration_flags_order['detectors']

        # Get the instrument flags
        for path in iflags_order:
            status = self.get_instrument_config_val(path)
            # If it is a list, loop through the values
            if isinstance(status, list):
                for entry in status:
                    statuses.append(entry)
            else:
                statuses.append(status)

        # Get the detector flags
        for name in self.detector_names:
            for path in dflags_order:
                if path[0] == 'distortion':
                    # Special case for distortion parameters
                    func_path = ['detectors', name, 'distortion',
                                 'function_name', 'value']
                    func_name = self.get_instrument_config_val(func_path)
                    if func_name == 'None':
                        # There is no distortion. Just continue.
                        continue

                    full_path = ['detectors', name] + path
                    status = self.get_instrument_config_val(full_path)

                    num_params = self.num_distortion_parameters(func_name)
                    for i in range(num_params):
                        statuses.append(status[i])
                    continue

                full_path = ['detectors', name] + path
                status = self.get_instrument_config_val(full_path)

                # If it is a list, loop through the values
                if isinstance(status, list):
                    for entry in status:
                        statuses.append(entry)
                else:
                    statuses.append(status)

        return np.asarray(statuses)

    def set_statuses_from_prev_iconfig(self, prev_iconfig):
        # This function seems to be much faster than
        # "set_statuses_from_instrument_format"
        self._recursive_set_statuses(self.config['instrument'], prev_iconfig)

    def _recursive_set_statuses(self, cur, prev):
        # Only use keys that both of them have
        keys = set(cur.keys()) & set(prev.keys())
        for key in keys:
            if isinstance(cur[key], dict) and isinstance(prev[key], dict):
                if 'status' in cur[key] and 'status' in prev[key]:
                    cur[key]['status'] = prev[key]['status']
                    continue

                self._recursive_set_statuses(cur[key], prev[key])

    def set_statuses_from_instrument_format(self, statuses):
        """This sets statuses using the hexrd instrument format"""
        # FIXME: This function is really slow for some reason. We are
        # currently using "set_statuses_from_prev_iconfig" instead.
        # If we ever want to use this function again, let's try to make
        # it much faster.

        cur_ind = 0

        iflags_order = self.calibration_flags_order['instrument']
        dflags_order = self.calibration_flags_order['detectors']

        # Set the instrument flags
        for path in iflags_order:
            prev_val = self.get_instrument_config_val(path)
            # If it is a list, loop through the values
            if isinstance(prev_val, list):
                for i in range(len(prev_val)):
                    v = statuses[cur_ind]
                    self.set_instrument_config_val(path + [i], v)
                    cur_ind += 1
            else:
                v = statuses[cur_ind]
                self.set_instrument_config_val(path, v)
                cur_ind += 1

        # Set the detector flags
        for name in self.detector_names:
            for path in dflags_order:
                full_path = ['detectors', name] + path

                if path[0] == 'distortion':
                    # Special case for distortion parameters
                    func_path = ['detectors', name, 'distortion',
                                 'function_name', 'value']
                    func_name = self.get_instrument_config_val(func_path)
                    num_params = self.num_distortion_parameters(func_name)
                    for i in range(num_params):
                        v = statuses[cur_ind]
                        self.set_instrument_config_val(full_path + [i], v)
                        cur_ind += 1
                    continue

                prev_val = self.get_instrument_config_val(full_path)

                # If it is a list, loop through the values
                if isinstance(prev_val, list):
                    for i in range(len(prev_val)):
                        v = statuses[cur_ind]
                        self.set_instrument_config_val(full_path + [i], v)
                        cur_ind += 1
                else:
                    v = statuses[cur_ind]
                    self.set_instrument_config_val(full_path, v)
                    cur_ind += 1

    def _search_gui_yaml_dict(self, d, res, cur_path=None):
        """This recursive function gets all yaml paths to GUI variables

        res is a list of results that will contain a tuple of GUI
        variables to paths. The GUI variables are assumed to start
        with 'cal_' for calibration.

        For instance, it will contain
        ("cal_energy", [ "beam", "energy" ] ), which means that
        the path to the default value of "cal_energy" is
        self.config['instrument']["beam"]["energy"]
        """
        if cur_path is None:
            cur_path = []

        for key, value in d.items():
            if isinstance(value, dict):
                new_cur_path = cur_path + [key]
                self._search_gui_yaml_dict(d[key], res, new_cur_path)
            elif isinstance(value, list):
                for i, element in enumerate(value):
                    if isinstance(element, str) and element.startswith('cal_'):
                        res.append((element, cur_path + [key, 'value', i]))
            else:
                if isinstance(value, str) and value.startswith('cal_'):
                    res.append((value, cur_path + [key, 'value']))

    def get_gui_yaml_paths(self, path=None):
        """This returns all GUI variables along with their paths

        It assumes that all GUI variables start with 'cal_' for
        calibration.

        If the path argument is passed as well, it will only search
        the subset of the dictionary for GUI variables.

        For instance, the returned list may contain
        ("cal_energy", [ "beam", "energy" ] ), which means that
        the path to the default value of "cal_energy" is
        self.config['instrument']["beam"]["energy"]
        """
        search_dict = self.gui_yaml_dict
        if path is not None:
            for item in path:
                search_dict = search_dict[item]
        else:
            path = []

        string_path = str(path)
        if string_path in self.cached_gui_yaml_dicts.keys():
            return copy.deepcopy(self.cached_gui_yaml_dicts[string_path])

        res = []
        self._search_gui_yaml_dict(search_dict, res)
        self.cached_gui_yaml_dicts[string_path] = res
        return res

    def set_instrument_config_val(self, path, value):
        """This sets a value from a path list."""
        cur_val = self.config['instrument']

        # Special case for distortion:
        # If it is None, remove the distortion dict
        # If it is not None, then create the distortion dict if not present
        dist_func_path = ['distortion', 'function_name', 'value']
        if len(path) > 4 and path[2:5] == dist_func_path:
            cur_val = cur_val[path[0]][path[1]]
            if value == 'None' and 'distortion' in cur_val:
                del cur_val['distortion']
            elif value != 'None':
                cur_val['distortion'] = {
                    'function_name': value,
                    'parameters': (
                        [0.] * self.num_distortion_parameters(value)
                    )
                }
                self.add_status(cur_val['distortion'])
            return

        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            cur_val[path[-1]] = value
        except KeyError:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.config['instrument']))
            raise Exception(msg)

        if 'status' in path[-2:]:
            # If we are just modifying a status, we are done
            return

        # If the beam energy was modified, update the visible materials
        if path == ['beam', 'energy', 'value']:
            self.update_visible_material_energies()
            return

        if path[:2] == ['beam', 'vector']:
            # Beam vector has been modified. Indicate so.
            self.beam_vector_changed.emit()
            return

        if path[0] == 'detectors' and path[2] == 'transform':
            # If a detector transform was modified, send a signal
            # indicating so
            det = path[1]
            self.detector_transform_modified.emit(det)
            return

        # Otherwise, assume we need to re-render the whole image
        self.rerender_needed.emit()

    def get_instrument_config_val(self, path):
        """This obtains a dict value from a path list.

        For instance, if path is [ "beam", "energy" ], it will
        return self.config['instrument']["beam"]["energy"]

        """
        cur_val = self.config['instrument']

        # Special case for distortion:
        # If no distortion is specified, return 'None'
        dist_func_path = ['distortion', 'function_name']
        if len(path) > 3 and path[2:4] == dist_func_path:
            for val in path:
                if val not in cur_val:
                    return 'None' if path[-1] == 'value' else 1
                cur_val = cur_val[val]
            return cur_val

        try:
            for val in path:
                cur_val = cur_val[val]
        except KeyError:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.config['instrument']))
            raise Exception(msg)

        return cur_val

    def set_val_from_widget_name(self, widget_name, value, detector=None):
        yaml_paths = self.get_gui_yaml_paths()
        for var, path in yaml_paths:
            if var == widget_name:
                if 'detector_name' in path:
                    # Replace detector_name with the detector name
                    path[path.index('detector_name')] = detector

                    if self.rotation_matrix_euler() is not None:
                        tilt_path = ['transform', 'tilt', 'value']
                        if path[2:-1] == tilt_path:
                            # This will be in degrees. Convert to radians.
                            value = np.radians(value).item()

                self.set_instrument_config_val(path, value)
                return

        raise Exception(widget_name + ' was not found in instrument_config!')

    def get_detector_widgets(self):
        # These ones won't be found in the gui yaml dict
        res = [
            ('cal_det_current',),
            ('cal_det_add',),
            ('cal_det_remove',)
        ]
        res += self.get_gui_yaml_paths(['detectors'])
        return [x[0] for x in res]

    @property
    def detector_names(self):
        return list(self.config['instrument'].get('detectors', {}).keys())

    @property
    def detectors(self):
        return self.config['instrument'].get('detectors', {})

    def detector(self, detector_name):
        return self.config['instrument']['detectors'][detector_name]

    @property
    def default_detector(self):
        return copy.deepcopy(
            self.default_config['instrument']['detectors']['detector_1'])

    def detector_pixel_size(self, detector_name):
        detector = self.detector(detector_name)
        pixel_size = detector.get('pixels', {}).get('size', {})
        return pixel_size.get('value', [0.1, 0.1])

    def add_detector(self, detector_name, detector_to_copy=None):
        if detector_to_copy is not None:
            new_detector = copy.deepcopy(self.detector(detector_to_copy))
        else:
            new_detector = self.default_detector

        self.config['instrument']['detectors'][detector_name] = new_detector
        self.detectors_changed.emit()

    def remove_detector(self, detector_name):
        del self.config['instrument']['detectors'][detector_name]
        self.detectors_changed.emit()

    def rename_detector(self, old_name, new_name):
        if old_name != new_name:
            self.config['instrument']['detectors'][new_name] = (
                self.config['instrument']['detectors'][old_name])
            self.remove_detector(old_name)

    # This section is for materials configuration
    def load_default_materials(self):
        module = hexrd.ui.resources.materials
        with resource_loader.path(module, 'materials.h5') as file_path:
            self.load_materials(str(file_path))

        # Set the tth_max of all the materials to match that of the polar
        # resolution config.
        self.reset_tth_max_all_materials()

    def add_material(self, name, material):
        if name in self.materials:
            raise Exception(name + ' is already in materials list!')
        self.config['materials']['materials'][name] = material
        self.reset_tth_max(name)

    def rename_material(self, old_name, new_name):
        if old_name != new_name:
            self.config['materials']['materials'][new_name] = (
                self.config['materials']['materials'][old_name])
            self.config['materials']['materials'][new_name].name = new_name

            # Rename any overlays as well
            for overlay in self.overlays:
                if overlay['material'] == old_name:
                    overlay['material'] = new_name

            if self.active_material_name == old_name:
                # Change the active material before removing the old one
                # Set the dict directly to bypass the updates that occur
                # if we did self.active_material = new_name
                self.config['materials']['active_material'] = new_name

            # Avoid calling self.remove_material() to avoid pruning
            # overlays and such.
            del self.config['materials']['materials'][old_name]

            self.material_renamed.emit()

    def modify_material(self, name, material):
        if name not in self.materials:
            raise Exception(name + ' is not in materials list!')
        self.config['materials']['materials'][name] = material

        self.flag_overlay_updates_for_material(name)
        self.overlay_config_changed.emit()

    def remove_material(self, name):
        if name not in self.materials:
            raise Exception(name + ' is not in materials list!')
        del self.config['materials']['materials'][name]
        self.prune_overlays()

        if name == self.active_material_name:
            if self.materials.keys():
                self.active_material = list(self.materials.keys())[0]
            else:
                self.active_material = None

        self.material_removed.emit()

    def _materials(self):
        return self.config['materials'].get('materials', {})

    def _set_materials(self, materials):
        self.config['materials']['materials'] = materials
        if materials.keys():
            self.active_material = list(materials.keys())[0]

        self.prune_overlays()
        self.flag_overlay_updates_for_all_materials()
        self.overlay_config_changed.emit()

    materials = property(_materials, _set_materials)

    def material(self, name):
        return self.config['materials']['materials'].get(name)

    def _active_material(self):
        m = self.active_material_name
        return self.material(m)

    def _set_active_material(self, name):
        if name not in self.materials and name is not None:
            raise Exception(name + ' was not found in materials list: ' +
                            str(self.materials))

        self.config['materials']['active_material'] = name
        self.update_active_material_energy()
        self.active_material_changed.emit()

    active_material = property(_active_material, _set_active_material)

    @property
    def active_material_name(self):
        return self.config['materials'].get('active_material')

    @property
    def beam_energy(self):
        cfg = self.config['instrument']
        return cfg.get('beam', {}).get('energy', {}).get('value')

    @property
    def beam_wavelength(self):
        energy = self.beam_energy
        return constants.KEV_TO_WAVELENGTH / energy if energy else None

    def update_material_energy(self, mat):
        # This is a potentially expensive operation...
        energy = self.beam_energy

        # If the plane data energy already matches, skip it
        pd_wavelength = mat.planeData.get_wavelength()
        old_energy = constants.WAVELENGTH_TO_KEV / pd_wavelength

        # If these are rounded to 5 decimal places instead of 4, this
        # always fails. Maybe we are using a slightly different constant
        # than hexrd uses?
        if round(old_energy, 4) == round(energy, 4):
            return

        mat.beamEnergy = energy
        utils.make_new_pdata(mat)
        self.flag_overlay_updates_for_material(mat.name)

    def update_active_material_energy(self):
        self.update_material_energy(self.active_material)
        self.new_plane_data.emit()
        self.overlay_config_changed.emit()

    def update_visible_material_energies(self):
        for mat in self.visible_materials:
            self.update_material_energy(mat)

        self.new_plane_data.emit()
        self.overlay_config_changed.emit()

    def material_is_visible(self, name):
        return name in self.visible_material_names

    @property
    def visible_materials(self):
        names = self.visible_material_names
        return [v for k, v in self.materials.items() if k in names]

    @property
    def visible_material_names(self):
        if not self.show_overlays:
            return []

        return list({x['material'] for x in self.overlays if x['visible']})

    def reset_tth_max(self, material_name):
        # Sets the tth_max of the material to match that of the polar
        # resolution. Does not emit "overlay_config_changed".
        tth_max = np.radians(self.polar_res_tth_max)
        mat = self.material(material_name)
        plane_data = mat.planeData
        if tth_max == plane_data.tThMax:
            return

        plane_data.tThMax = tth_max
        self.flag_overlay_updates_for_material(material_name)

        if mat is self.active_material:
            self.active_material_modified.emit()

    def reset_tth_max_all_materials(self):
        # Sets the tth max of all materials to match that of the
        # polar resolution.
        for name in self.materials.keys():
            self.reset_tth_max(name)

        self.overlay_config_changed.emit()

    def _active_material_tth_max(self):
        return self.active_material.planeData.tThMax

    def _set_active_material_tth_max(self, v):
        # v should be in radians
        if v != self.active_material_tth_max:
            if v is None:
                self.backup_tth_max = self.active_material_tth_max

            self.active_material.planeData.tThMax = v
            self.flag_overlay_updates_for_active_material()
            self.overlay_config_changed.emit()

    active_material_tth_max = property(_active_material_tth_max,
                                       _set_active_material_tth_max)

    def _backup_tth_max(self):
        return self.backup_tth_maxes.setdefault(self.active_material_name, 1.0)

    def _set_backup_tth_max(self, v):
        self.backup_tth_maxes[self.active_material_name] = v

    backup_tth_max = property(_backup_tth_max, _set_backup_tth_max)

    def _limit_active_rings(self):
        return self.active_material_tth_max is not None

    def set_limit_active_rings(self, v):
        # This will restore the backup of tth max, or set tth max to None
        if v != self.limit_active_rings:
            if v:
                self.active_material_tth_max = self.backup_tth_max
            else:
                self.active_material_tth_max = None

    limit_active_rings = property(_limit_active_rings,
                                  set_limit_active_rings)

    def _show_overlays(self):
        return self.config['materials'].get('show_overlays')

    def _set_show_overlays(self, b):
        if b != self.show_overlays:
            self.config['materials']['show_overlays'] = b
            self.overlay_config_changed.emit()

    show_overlays = property(_show_overlays, _set_show_overlays)

    def prune_overlays(self):
        # Removes overlays for which we do not have a material
        mats = list(self.materials.keys())
        self.overlays = [x for x in self.overlays if x['material'] in mats]
        self.overlay_config_changed.emit()

    def append_overlay(self, material_name, type, style=None, visible=True):
        if style is None:
            style = overlays.default_overlay_style(type)

        overlay = {
            'material': material_name,
            'type': type,
            'style': style,
            'visible': visible,
            'options': overlays.default_overlay_options(type),
            'refinements': overlays.default_overlay_refinements(type),
            'data': {}
        }
        self.overlays.append(overlay)
        self.overlay_config_changed.emit()

    def change_overlay_type(self, i, type):
        if not 0 <= i < len(self.overlays):
            # Out of range
            return

        overlay = self.overlays[i]
        if overlay['type'] == type:
            # No change needed
            return

        overlay['type'] = type
        overlay['style'] = overlays.default_overlay_style(type)
        overlay['options'] = overlays.default_overlay_options(type)
        overlay['refinements'] = overlays.default_overlay_refinements(type)
        overlay['update_needed'] = True

    def clear_overlay_data(self):
        for overlay in self.overlays:
            overlay['data'].clear()
            if 'update_needed' in overlay:
                del overlay['update_needed']
            if 'highlights' in overlay:
                del overlay['highlights']

    def flag_overlay_updates_for_active_material(self):
        self.flag_overlay_updates_for_material(self.active_material_name)

    def flag_overlay_updates_for_material(self, material_name):
        for overlay in self.overlays:
            if overlay['material'] == material_name:
                overlay['update_needed'] = True

    def flag_overlay_updates_for_all_materials(self):
        for name in self.materials:
            self.flag_overlay_updates_for_material(name)

    @property
    def visible_polar_masks(self):
        masks = self.polar_masks.items()
        visible = self.visible_masks
        return [mask for name, mask in masks if name in visible]

    def _polar_pixel_size_tth(self):
        return self.config['image']['polar']['pixel_size_tth']

    def _set_polar_pixel_size_tth(self, v):
        self.config['image']['polar']['pixel_size_tth'] = v
        self.rerender_needed.emit()

    polar_pixel_size_tth = property(_polar_pixel_size_tth,
                                    _set_polar_pixel_size_tth)

    def _polar_pixel_size_eta(self):
        return self.config['image']['polar']['pixel_size_eta']

    def _set_polar_pixel_size_eta(self, v):
        self.config['image']['polar']['pixel_size_eta'] = v
        self.rerender_needed.emit()

    polar_pixel_size_eta = property(_polar_pixel_size_eta,
                                    _set_polar_pixel_size_eta)

    def _polar_res_tth_min(self):
        return self.config['image']['polar']['tth_min']

    def set_polar_res_tth_min(self, v):
        self.config['image']['polar']['tth_min'] = v
        self.rerender_needed.emit()

    polar_res_tth_min = property(_polar_res_tth_min,
                                 set_polar_res_tth_min)

    def _polar_res_tth_max(self):
        return self.config['image']['polar']['tth_max']

    def set_polar_res_tth_max(self, v):
        self.config['image']['polar']['tth_max'] = v
        self.rerender_needed.emit()

    polar_res_tth_max = property(_polar_res_tth_max,
                                 set_polar_res_tth_max)

    def _polar_res_eta_min(self):
        return self.config['image']['polar']['eta_min']

    def set_polar_res_eta_min(self, v, rerender=True):
        self.config['image']['polar']['eta_min'] = v
        if rerender:
            self.rerender_needed.emit()

            # If we are drawing outside of the previous extents,
            # we will need to update the overlays as well.
            self.flag_overlay_updates_for_all_materials()
            self.overlay_config_changed.emit()

    polar_res_eta_min = property(_polar_res_eta_min,
                                 set_polar_res_eta_min)

    def _polar_res_eta_max(self):
        return self.config['image']['polar']['eta_max']

    def set_polar_res_eta_max(self, v, rerender=True):
        self.config['image']['polar']['eta_max'] = v
        if rerender:
            self.rerender_needed.emit()

            # If we are drawing outside of the previous extents,
            # we will need to update the overlays as well.
            self.flag_overlay_updates_for_all_materials()
            self.overlay_config_changed.emit()

    polar_res_eta_max = property(_polar_res_eta_max,
                                 set_polar_res_eta_max)

    @property
    def polar_res_eta_period(self):
        return self.polar_res_eta_min + np.r_[0., 360.]

    def _polar_apply_snip1d(self):
        return self.config['image']['polar']['apply_snip1d']

    def set_polar_apply_snip1d(self, v):
        self.config['image']['polar']['apply_snip1d'] = v
        self.rerender_needed.emit()

    polar_apply_snip1d = property(_polar_apply_snip1d,
                                  set_polar_apply_snip1d)

    def _polar_snip1d_algorithm(self):
        return self.config['image']['polar']['snip1d_algorithm']

    def set_polar_snip1d_algorithm(self, v):
        self.config['image']['polar']['snip1d_algorithm'] = v
        self.rerender_needed.emit()

    polar_snip1d_algorithm = property(_polar_snip1d_algorithm,
                                      set_polar_snip1d_algorithm)

    def _polar_snip1d_width(self):
        return self.config['image']['polar']['snip1d_width']

    def set_polar_snip1d_width(self, v):
        self.config['image']['polar']['snip1d_width'] = v
        self.rerender_needed.emit()

    polar_snip1d_width = property(_polar_snip1d_width,
                                  set_polar_snip1d_width)

    def _polar_snip1d_numiter(self):
        return self.config['image']['polar']['snip1d_numiter']

    def set_polar_snip1d_numiter(self, v):
        self.config['image']['polar']['snip1d_numiter'] = v
        self.rerender_needed.emit()

    polar_snip1d_numiter = property(_polar_snip1d_numiter,
                                    set_polar_snip1d_numiter)

    def _cartesian_pixel_size(self):
        return self.config['image']['cartesian']['pixel_size']

    def _set_cartesian_pixel_size(self, v):
        if v != self.cartesian_pixel_size:
            self.config['image']['cartesian']['pixel_size'] = v
            self.rerender_needed.emit()

    cartesian_pixel_size = property(_cartesian_pixel_size,
                                    _set_cartesian_pixel_size)

    def _cartesian_virtual_plane_distance(self):
        return self.config['image']['cartesian']['virtual_plane_distance']

    def set_cartesian_virtual_plane_distance(self, v):
        if v != self.cartesian_virtual_plane_distance:
            self.config['image']['cartesian']['virtual_plane_distance'] = v
            self.rerender_needed.emit()

    cartesian_virtual_plane_distance = property(
        _cartesian_virtual_plane_distance,
        set_cartesian_virtual_plane_distance)

    def _cartesian_plane_normal_rotate_x(self):
        return self.config['image']['cartesian']['plane_normal_rotate_x']

    def set_cartesian_plane_normal_rotate_x(self, v):
        if v != self.cartesian_plane_normal_rotate_x:
            self.config['image']['cartesian']['plane_normal_rotate_x'] = v
            self.rerender_needed.emit()

    cartesian_plane_normal_rotate_x = property(
        _cartesian_plane_normal_rotate_x,
        set_cartesian_plane_normal_rotate_x)

    def _cartesian_plane_normal_rotate_y(self):
        return self.config['image']['cartesian']['plane_normal_rotate_y']

    def set_cartesian_plane_normal_rotate_y(self, v):
        if v != self.cartesian_plane_normal_rotate_y:
            self.config['image']['cartesian']['plane_normal_rotate_y'] = v
            self.rerender_needed.emit()

    cartesian_plane_normal_rotate_y = property(
        _cartesian_plane_normal_rotate_y,
        set_cartesian_plane_normal_rotate_y)

    def get_show_saturation_level(self):
        return self._show_saturation_level

    def set_show_saturation_level(self, v):
        if self._show_saturation_level != v:
            self._show_saturation_level = v
            self.show_saturation_level_changed.emit()

    show_saturation_level = property(get_show_saturation_level,
                                     set_show_saturation_level)

    def tab_images(self):
        return self._tab_images

    def set_tab_images(self, v):
        if self._tab_images != v:
            self._tab_images = v
            self.tab_images_changed.emit()

    tab_images = property(tab_images, set_tab_images)

    def set_euler_angle_convention(self, new_conv, convert_config=True):

        allowed_conventions = [
            {
                'axes_order': 'xyz',
                'extrinsic': True
            },
            {
                'axes_order': 'zxz',
                'extrinsic': False
            },
            None
        ]

        if new_conv not in allowed_conventions:
            default_conv = constants.DEFAULT_EULER_ANGLE_CONVENTION
            print('Warning: Euler angle convention not allowed:', new_conv)
            print('Setting the default instead:', default_conv)
            new_conv = default_conv

        if convert_config:
            # First, convert all the tilt angles
            old_conv = self._euler_angle_convention
            utils.convert_tilt_convention(self.config['instrument'], old_conv,
                                          new_conv)

        # Set the variable
        self._euler_angle_convention = copy.deepcopy(new_conv)
        self.euler_angle_convention_changed.emit()

    @property
    def instrument_config_none_euler_convention(self):
        iconfig = self.instrument_config
        eac = self.euler_angle_convention
        utils.convert_tilt_convention(iconfig, eac, None)
        return iconfig

    @property
    def euler_angle_convention(self):
        return self._euler_angle_convention

    def rotation_matrix_euler(self):
        convention = self.euler_angle_convention
        if convention is None:
            return None

        return RotMatEuler(np.zeros(3), **convention)

    @property
    def show_detector_borders(self):
        return self.config['image']['show_detector_borders']

    def set_show_detector_borders(self, v):
        if v != self.show_detector_borders:
            self.config['image']['show_detector_borders'] = v
            self.rerender_detector_borders.emit()

    @staticmethod
    def num_distortion_parameters(func_name):
        if func_name == 'None':
            return 0
        elif func_name == 'GE_41RT':
            return 6

        raise Exception('Unknown distortion function: ' + func_name)

    def threshold_comparison(self):
        if 'comparison' not in self._threshold_data:
            self._threshold_data['comparison'] = 0
        return self._threshold_data['comparison']

    def threshold_value(self):
        if 'value' not in self._threshold_data:
            self._threshold_data['value'] = 0.0
        return self._threshold_data['value']

    def threshold_mask_status(self):
        if 'mask_status' not in self._threshold_data:
            self._threshold_data['mask_status'] = False
        return self._threshold_data['mask_status']

    def threshold_mask(self):
        if 'mask' not in self._threshold_data:
            self._threshold_data['mask'] = None
        return self._threshold_data['mask']

    def set_threshold_comparison(self, v):
        self._threshold_data['comparison'] = v

    def set_threshold_value(self, v):
        self._threshold_data['value'] = v

    def set_threshold_mask_status(self, v, set_by_mgr=False):
        if set_by_mgr and self._threshold_data['mask_status'] != v:
            self.mgr_threshold_mask_changed.emit(v)
            self._threshold_data['mask_status'] = v
        elif not set_by_mgr and self._threshold_data['mask_status'] != v:
            self.mode_threshold_mask_changed.emit(v)
            self._threshold_data['mask_status'] = v

    def set_threshold_mask(self, m):
        self._threshold_data['mask'] = m

    threshold_comparison = property(threshold_comparison,
                                    set_threshold_comparison)
    threshold_value = property(threshold_value,
                               set_threshold_value)
    threshold_mask_status = property(threshold_mask_status,
                                     set_threshold_mask_status)
    threshold_mask = property(threshold_mask,
                              set_threshold_mask)

    @property
    def display_wppf_plot(self):
        settings = HexrdConfig().config['calibration'].setdefault('wppf', {})
        return settings.setdefault('display_plot', True)

    @display_wppf_plot.setter
    def display_wppf_plot(self, b):
        if self.display_wppf_plot != b:
            settings = HexrdConfig().config['calibration']['wppf']
            settings['display_plot'] = b
            self.rerender_wppf.emit()
