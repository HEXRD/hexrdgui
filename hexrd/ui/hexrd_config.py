import copy
import math
import pickle

from PySide2.QtCore import Signal, QCoreApplication, QObject, QSettings

import numpy as np
import yaml

import hexrd.imageseries.save
from hexrd.rotations import RotMatEuler

from hexrd.ui import constants
from hexrd.ui import resource_loader
from hexrd.ui import utils

import hexrd.ui.resources.calibration
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

    """Emitted when ring configuration has changed"""
    ring_config_changed = Signal()

    """Emitted when the option to show the saturation level is changed"""
    show_saturation_level_changed = Signal()

    """Emitted when the option to tab images is changed"""
    tab_images_changed = Signal()

    """Emitted when a detector's transform is modified"""
    detector_transform_modified = Signal(str)

    """Emitted when detector borders need to be re-rendered"""
    rerender_detector_borders = Signal()

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

    """Emitted when an instrument config has been loaded"""
    instrument_config_loaded = Signal()

    """Convenience signal to update the main window's status bar

    Arguments are: message (str)

    """
    update_status_bar = Signal(str)

    """Emitted when the load_panel_state has been cleared"""
    load_panel_state_reset = Signal()

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
        self.polar_masks = []
        self.ring_styles = {}
        self.backup_tth_maxes = {}
        self.backup_tth_widths = {}

        self.set_euler_angle_convention('xyz', True, convert_config=False)

        # Load default configuration settings
        self.load_default_config()

        self.config['materials'] = copy.deepcopy(
            self.default_config['materials'])
        self.config['image'] = copy.deepcopy(self.default_config['image'])

        if '--ignore-settings' not in QCoreApplication.arguments():
            self.load_settings()

        if self.config.get('instrument') is None:
            # Load the default config['instrument'] settings
            self.config['instrument'] = copy.deepcopy(
                self.default_config['instrument'])

        if self.config.get('calibration') is None:
            self.config['calibration'] = copy.deepcopy(
                self.default_config['calibration'])

        # Set required defaults if any are missing
        self.set_defaults_if_missing()

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
        settings.setValue('images_dir', self.images_dir)
        settings.setValue('hdf5_path', self.hdf5_path)
        settings.setValue('live_update', self.live_update)
        settings.setValue('euler_angle_convention', self.euler_angle_convention)
        settings.setValue('active_material', self.active_material_name)
        settings.setValue('collapsed_state', self.collapsed_state)
        settings.setValue('load_panel_state', self.load_panel_state)
        settings.setValue('ring_styles', self.ring_styles)
        settings.setValue('visible_material_names',
                          self.visible_material_names)

    def load_settings(self):
        settings = QSettings()
        self.config['instrument'] = settings.value('config_instrument', None)
        self.config['calibration'] = settings.value('config_calibration', None)
        self.images_dir = settings.value('images_dir', None)
        self.hdf5_path = settings.value('hdf5_path', None)
        # All QSettings come back as strings.
        self.live_update = settings.value('live_update', 'true') == 'true'

        conv = settings.value('euler_angle_convention', ('xyz', True))
        self.set_euler_angle_convention(conv[0], conv[1], convert_config=False)

        self.previous_active_material = settings.value('active_material', None)
        self.collapsed_state = settings.value('collapsed_state', [])
        self.load_panel_state = settings.value('load_panel_state', {})
        self.ring_styles = settings.value('ring_styles', {})

        # Set this manually since we don't have any materials yet
        key = 'visible_material_names'
        self.config['materials'][key] = settings.value(key, [])

        # This will not be a list if only one material was on it
        # Make sure it is a list
        if not isinstance(self.config['materials'][key], list):
            self.config['materials'][key] = [self.config['materials'][key]]

        # Saving an empty list and then loading it results in [None]
        # for some reason
        if self.config['materials'][key] == [None]:
            self.config['materials'][key] = []

    def emit_update_status_bar(self, msg):
        """Convenience signal to update the main window's status bar"""
        self.update_status_bar.emit(msg)

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
        self.config['instrument'] = copy.deepcopy(
            self.instrument_config_backup)

        old_eac = self.instrument_config_backup_eac
        new_eac = self.euler_angle_convention
        if old_eac != new_eac:
            # Convert it to whatever convention we are using
            utils.convert_tilt_convention(self.config['instrument'], old_eac,
                                          new_eac)

        self.deep_rerender_needed.emit()
        self.update_visible_material_energies()
        self.instrument_config_loaded.emit()

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
        to_do_keys = ['instrument', 'calibration', 'image']
        for key in to_do_keys:
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

    def save_imageseries(self, ims, name, write_file, selected_format, **kwargs):
        hexrd.imageseries.save.write(ims, write_file, selected_format,
                                     **kwargs)

    def clear_images(self, initial_load=False):
        self.imageseries_dict.clear()
        self.hdf5_path = None
        if self.load_panel_state is not None and not initial_load:
            self.load_panel_state.clear()
            self.load_panel_state_reset.emit()

    def load_instrument_config(self, yml_file):
        old_detectors = self.detector_names
        with open(yml_file, 'r') as f:
            self.config['instrument'] = yaml.load(f, Loader=yaml.FullLoader)

        eac = self.euler_angle_convention
        if eac != (None, None):
            # Convert it to whatever convention we are using
            old_conv = (None, None)
            utils.convert_tilt_convention(self.config['instrument'], old_conv,
                                          eac)

        # Set any required keys that might be missing to prevent key errors
        self.set_defaults_if_missing()
        self.create_internal_config(self.config['instrument'])

        # Create a backup
        self.backup_instrument_config()

        self.update_visible_material_energies()

        new_detectors = self.detector_names
        if old_detectors != new_detectors:
            self.detectors_changed.emit()
        else:
            # Still need a deep rerender
            self.deep_rerender_needed.emit()

        self.instrument_config_loaded.emit()
        return self.config['instrument']

    def save_instrument_config(self, output_file):
        default = self.filter_instrument_config(self.config['instrument'])
        eac = self.euler_angle_convention
        if eac != (None, None):
            # Convert it to None convention before saving
            new_conv = (None, None)
            utils.convert_tilt_convention(default, eac, new_conv)

        with open(output_file, 'w') as f:
            yaml.dump(default, f)

    def load_materials(self, f):
        with open(f, 'rb') as rf:
            data = rf.read()
        self.load_materials_from_binary(data)

    def save_materials(self, f):
        with open(f, 'wb') as wf:
            pickle.dump(list(self.materials.values()), wf)

    def set_live_update(self, status):
        self.live_update = status

    def create_internal_config(self, cur_config):
        if not self.has_status(cur_config):
            self.add_status(cur_config)

    def filter_instrument_config(self, cur_config):
        # Filters the refined status values out of the
        # intrument config tree
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
                    stat_default = [1] * len(value)
                else:
                    stat_default = 1
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
                full_path = ['detectors', name] + path
                status = self.get_instrument_config_val(full_path)

                if path[0] == 'distortion':
                    # Special case for distortion parameters
                    func_path = ['detectors', name, 'distortion',
                                 'function_name', 'value']
                    func_name = self.get_instrument_config_val(func_path)
                    num_params = self.num_distortion_parameters(func_name)
                    for i in range(num_params):
                        statuses.append(status[i])
                    continue

                # If it is a list, loop through the values
                if isinstance(status, list):
                    for entry in status:
                        statuses.append(entry)
                else:
                    statuses.append(status)

        # Finally, reverse all booleans. We use "fixed", but they use
        # "refinable".
        statuses = [not x for x in statuses]
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

        # First, make a deep copy, and then reverse all booleans. We
        # use "fixed", but they use "refinable"
        statuses = copy.deepcopy(statuses)
        statuses = [not x for x in statuses]

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
        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            cur_val[path[-1]] = value
        except:
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
        try:
            for val in path:
                cur_val = cur_val[val]
        except:
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
            self.default_config['instrument']['detectors']['ge1'])

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
        data = resource_loader.load_resource(hexrd.ui.resources.materials,
                                             'materials.hexrd', binary=True)
        self.load_materials_from_binary(data)

    def load_materials_from_binary(self, data):
        matlist = pickle.loads(data, encoding='latin1')
        materials = dict(zip([i.name for i in matlist], matlist))

        # For some reason, the default materials do not have the same beam
        # energy as their plane data. We need to fix this.
        for material in materials.values():
            pd_wavelength = material.planeData.get_wavelength()
            material._beamEnergy = constants.WAVELENGTH_TO_KEV / pd_wavelength

        # Make sure all materials on the visible materials list exist
        material_names = materials.keys()
        self.visible_material_names = [
            x for x in self.visible_material_names if x in material_names]

        self.materials = materials

    def add_material(self, name, material):
        if name in self.materials:
            raise Exception(name + ' is already in materials list!')
        self.config['materials']['materials'][name] = material

    def rename_material(self, old_name, new_name):
        if old_name != new_name:
            self.config['materials']['materials'][new_name] = (
                self.config['materials']['materials'][old_name])
            self.config['materials']['materials'][new_name].name = new_name

            # Transfer the styles over as well
            if old_name in self.ring_styles:
                self.ring_styles[new_name] = self.ring_styles.pop(old_name)

            if old_name in self.visible_material_names:
                idx = self.visible_material_names.index(old_name)
                self.visible_material_names[idx] = new_name

            if self.active_material_name == old_name:
                # Change the active material before removing the old one
                self.active_material = new_name

            self.remove_material(old_name)

    def modify_material(self, name, material):
        if name not in self.materials:
            raise Exception(name + ' is not in materials list!')
        self.config['materials']['materials'][name] = material

        if self.material_is_visible(name):
            self.ring_config_changed.emit()

    def remove_material(self, name):
        if name not in self.materials:
            raise Exception(name + ' is not in materials list!')
        del self.config['materials']['materials'][name]

        if name in self.ring_styles:
            del self.ring_styles[name]

        if name in self.visible_material_names:
            self.visible_material_names.remove(name)

        if name == self.active_material_name:
            if self.materials.keys():
                self.active_material = list(self.materials.keys())[0]
            else:
                self.active_material = None

    def _materials(self):
        return self.config['materials'].get('materials', {})

    def _set_materials(self, materials):
        self.config['materials']['materials'] = materials
        if materials.keys():
            self.active_material = list(materials.keys())[0]

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
        self.ring_config_changed.emit()

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

    def update_active_material_energy(self):
        self.update_material_energy(self.active_material)
        self.new_plane_data.emit()
        self.ring_config_changed.emit()

    def update_visible_material_energies(self):
        for mat in self.visible_materials:
            self.update_material_energy(mat)

        self.new_plane_data.emit()
        self.ring_config_changed.emit()

    def material_is_visible(self, name):
        return name in self.visible_material_names

    def set_material_visibility(self, name, visible):
        if visible and name not in self.visible_material_names:
            self.visible_material_names.append(name)
            self.update_visible_material_energies()
        elif not visible and name in self.visible_material_names:
            self.visible_material_names.remove(name)
            self.update_visible_material_energies()

    @property
    def visible_materials(self):
        mats = []
        for name in self.visible_material_names:
            # Confirm that it exists
            if name in self.materials:
                mats.append(self.materials[name])

        return mats

    def _visible_material_names(self):
        return self.config['materials'].setdefault('visible_material_names',
                                                   [])

    def _set_visible_material_names(self, v):
        if v != self.visible_material_names:
            self.config['materials']['visible_material_names'] = v
            self.update_visible_material_energies()
            self.ring_config_changed.emit()

    visible_material_names = property(_visible_material_names,
                                      _set_visible_material_names)

    def _active_material_tth_width(self):
        return self.active_material.planeData.tThWidth

    def set_active_material_tth_width(self, v):
        if v != self.active_material_tth_width:
            if v is None:
                self.backup_tth_width = self.active_material_tth_width

            self.active_material.planeData.tThWidth = v
            self.ring_config_changed.emit()

    active_material_tth_width = property(_active_material_tth_width,
                                         set_active_material_tth_width)

    def _backup_tth_width(self):
        return self.backup_tth_widths.setdefault(self.active_material_name,
                                                 0.002182)

    def _set_backup_tth_width(self, v):
        self.backup_tth_widths[self.active_material_name] = v

    backup_tth_width = property(_backup_tth_width, _set_backup_tth_width)

    def _tth_width_enabled(self):
        return self.active_material_tth_width is not None

    def set_tth_width_enabled(self, v):
        # This will restore the backup of tth width, or set tth width to None
        if v != self.tth_width_enabled:
            if v:
                self.active_material_tth_width = self.backup_tth_width
            else:
                self.active_material_tth_width = None

    tth_width_enabled = property(_tth_width_enabled,
                                 set_tth_width_enabled)

    def _active_material_tth_max(self):
        return self.active_material.planeData.tThMax

    def _set_active_material_tth_max(self, v):
        if v != self.active_material_tth_max:
            if v is None:
                self.backup_tth_max = self.active_material_tth_max

            self.active_material.planeData.tThMax = v
            self.ring_config_changed.emit()

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
        self.config['materials']['show_overlays'] = b
        self.ring_config_changed.emit()

    show_overlays = property(_show_overlays, _set_show_overlays)

    def get_ring_style(self, name):
        # This will set defaults if no settings have been created
        style = self.ring_styles.setdefault(name, {})

        # Make sure any missing entries get set to default
        style.setdefault('ring_color', '#00ffff') # Cyan
        style.setdefault('ring_linestyle', 'solid')
        style.setdefault('ring_linewidth', 1.0)
        style.setdefault('rbnd_color', '#00ff00') # Green
        style.setdefault('rbnd_linestyle', 'dotted')
        style.setdefault('rbnd_linewidth', 1.0)

        return style

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

    def _polar_apply_snip1d(self):
        return self.config['image']['polar']['apply_snip1d']

    def set_polar_apply_snip1d(self, v):
        self.config['image']['polar']['apply_snip1d'] = v
        self.rerender_needed.emit()

    polar_apply_snip1d = property(_polar_apply_snip1d,
                                  set_polar_apply_snip1d)

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

    def set_euler_angle_convention(self, axes_order='xyz', extrinsic=True,
                                   convert_config=True):

        new_conv = (axes_order, extrinsic)

        allowed_combinations = [
            ('xyz', True),
            ('zxz', False),
            (None, None)
        ]

        if new_conv not in allowed_combinations:
            print('Warning: Euler angle convention not allowed:', new_conv)
            print('Setting the default instead:', allowed_combinations[0])
            new_conv = allowed_combinations[0]

        if convert_config:
            # First, convert all the tilt angles
            old_conv = self._euler_angle_convention
            utils.convert_tilt_convention(self.config['instrument'], old_conv,
                                          new_conv)

        # Set the variable
        self._euler_angle_convention = new_conv

    @property
    def instrument_config_none_euler_convention(self):
        iconfig = self.instrument_config
        eac = self.euler_angle_convention
        utils.convert_tilt_convention(iconfig, eac, (None, None))
        return iconfig

    @property
    def euler_angle_convention(self):
        return self._euler_angle_convention

    def rotation_matrix_euler(self):
        axes, extrinsic = self.euler_angle_convention
        if axes is None or extrinsic is None:
            return None

        return RotMatEuler(np.zeros(3), axes, extrinsic)

    @property
    def show_detector_borders(self):
        return self.config['image']['show_detector_borders']

    def set_show_detector_borders(self, v):
        if v != self.show_detector_borders:
            self.config['image']['show_detector_borders'] = v
            self.rerender_detector_borders.emit()

    @property
    def colormap_min(self):
        return self.config['image']['colormap']['min']

    def set_colormap_min(self, v):
        self.config['image']['colormap']['min'] = v

    @staticmethod
    def num_distortion_parameters(func_name):
        if func_name == 'None':
            return 0
        elif func_name == 'GE_41RT':
            return 6

        raise Exception('Unknown distortion function: ' + func_name)
