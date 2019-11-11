import copy
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

    """Emitted for any config changes EXCEPT detector transform changes

    Indicates that the image needs to be re-drawn from scratch.

    """
    rerender_needed = Signal()

    """Emitted when detectors have been added or removed"""
    detectors_changed = Signal()

    """Convenience signal to update the main window's status bar

    Arguments are: message (str)

    """
    update_status_bar = Signal(str)

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
        self.load_panel_state = None

        self.set_euler_angle_convention('xyz', True, convert_config=False)

        if '--ignore-settings' not in QCoreApplication.arguments():
            self.load_settings()

        # Load default configuration settings
        self.load_default_config()

        self.config['materials'] = copy.deepcopy(
            self.default_config['materials'])
        self.config['image'] = copy.deepcopy(self.default_config['image'])

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

        self.update_plane_data_tth_width()
        self.update_active_material_energy()

    def save_settings(self):
        settings = QSettings()
        settings.setValue('config_instrument', self.config['instrument'])
        settings.setValue('config_calibration', self.config['calibration'])
        settings.setValue('images_dir', self.images_dir)
        settings.setValue('hdf5_path', self.hdf5_path)
        settings.setValue('live_update', self.live_update)
        settings.setValue('euler_angle_convention', self.euler_angle_convention)
        settings.setValue('active_material', self.active_material_name())
        settings.setValue('collapsed_state', self.collapsed_state)
        settings.setValue('load_panel_state', self.load_panel_state)

    def load_settings(self):
        settings = QSettings()
        self.config['instrument'] = settings.value('config_instrument', None)
        self.config['calibration'] = settings.value('config_calibration', None)
        self.images_dir = settings.value('images_dir', None)
        self.hdf5_path = settings.value('hdf5_path', None)
        # All QSettings come back as strings.
        self.live_update = bool(settings.value('live_update', True) == 'true')

        conv = settings.value('euler_angle_convention', ('xyz', True))
        self.set_euler_angle_convention(conv[0], conv[1], convert_config=False)

        self.previous_active_material = settings.value('active_material', None)
        self.collapsed_state = settings.value('collapsed_state', [])
        self.load_panel_state = settings.value('load_panel_state', None)

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

        self.rerender_needed.emit()
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

        # Find missing keys under detectors and set defaults for them
        default = self.get_default_detector()
        for name in self.get_detector_names():
            self._recursive_set_defaults(self.get_detector(name), default)

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

    def save_imageseries(self, name, write_file, selected_format, **kwargs):
        ims = self.imageseries(name)
        hexrd.imageseries.save.write(ims, write_file, selected_format,
                                     **kwargs)

    def load_instrument_config(self, yml_file):
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

        self.update_active_material_energy()
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
        det_names = self.get_detector_names()
        for name in det_names:
            for path in dflags_order:
                full_path = ['detectors', name] + path
                status = self.get_instrument_config_val(full_path)
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

    def set_statuses_from_instrument_format(self, statuses):
        """This sets statuses using the hexrd instrument format"""
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
        det_names = self.get_detector_names()
        for name in det_names:
            for path in dflags_order:
                full_path = ['detectors', name] + path
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

        # If the beam energy was modified, update the active material
        if path == ['beam', 'energy', 'value']:
            self.update_active_material_energy()

        # If a detector transform was modified, send a signal indicating so
        if path[0] == 'detectors' and path[2] == 'transform':
            det = path[1]
            self.detector_transform_modified.emit(det)
        else:
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

    def get_detector_names(self):
        return list(self.config['instrument'].get('detectors', {}).keys())

    def get_default_detector(self):
        return copy.deepcopy(
            self.default_config['instrument']['detectors']['ge1'])

    def get_detector(self, detector_name):
        return self.config['instrument']['detectors'][detector_name]

    def add_detector(self, detector_name, detector_to_copy=None):
        if detector_to_copy is not None:
            new_detector = copy.deepcopy(self.get_detector(detector_to_copy))
        else:
            new_detector = self.get_default_detector()

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

        self.materials = materials

    def add_material(self, name, material):
        if name in self.materials:
            raise Exception(name + ' is already in materials list!')
        self.config['materials']['materials'][name] = material

    def rename_material(self, old_name, new_name):
        if old_name != new_name:
            self.config['materials']['materials'][new_name] = (
                self.config['materials']['materials'][old_name])

            if self.active_material_name() == old_name:
                # Change the active material before removing the old one
                self.active_material = new_name

            self.remove_material(old_name)

    def modify_material(self, name, material):
        if name not in self.materials:
            raise Exception(name + ' is not in materials list!')
        self.config['materials']['materials'][name] = material

        if self.active_material_name() == name:
            self.ring_config_changed.emit()

    def remove_material(self, name):
        if name not in self.materials:
            raise Exception(name + ' is not in materials list!')
        del self.config['materials']['materials'][name]

        if name == self.active_material_name():
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
        m = self.active_material_name()
        return self.material(m)

    def _set_active_material(self, name):
        if name not in self.materials and name is not None:
            raise Exception(name + ' was not found in materials list: ' +
                            str(self.materials))

        self.config['materials']['active_material'] = name
        self.update_plane_data_tth_width()
        self.update_active_material_energy()
        self.ring_config_changed.emit()

    active_material = property(_active_material, _set_active_material)

    def active_material_name(self):
        return self.config['materials'].get('active_material')

    def update_active_material_energy(self):
        # This is a potentially expensive operation...
        cfg = self.config['instrument']
        energy = cfg.get('beam', {}).get('energy', {}).get('value')
        mat = self.active_material

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

        self.update_plane_data_tth_width()

        self.new_plane_data.emit()
        self.ring_config_changed.emit()

    def update_plane_data_tth_width(self):
        mat = self.active_material
        mat.planeData.tThWidth = np.radians(self.ring_ranges)

    def _selected_rings(self):
        return self.config['materials'].get('selected_rings')

    def _set_selected_rings(self, rings):
        self.config['materials']['selected_rings'] = rings
        self.ring_config_changed.emit()

    selected_rings = property(_selected_rings, _set_selected_rings)

    def _show_rings(self):
        return self.config['materials'].get('show_rings')

    def _set_show_rings(self, b):
        self.config['materials']['show_rings'] = b
        self.ring_config_changed.emit()

    show_rings = property(_show_rings, _set_show_rings)

    def _show_ring_ranges(self):
        return self.config['materials'].get('show_ring_ranges')

    def _set_show_ring_ranges(self, b):
        self.config['materials']['show_ring_ranges'] = b
        self.ring_config_changed.emit()

    show_ring_ranges = property(_show_ring_ranges, _set_show_ring_ranges)

    def _ring_ranges(self):
        return self.config['materials'].get('ring_ranges')

    def _set_ring_ranges(self, r):
        self.config['materials']['ring_ranges'] = r
        self.update_plane_data_tth_width()
        self.ring_config_changed.emit()

    ring_ranges = property(_ring_ranges, _set_ring_ranges)

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
        self.config['image']['cartesian']['pixel_size'] = v
        self.rerender_needed.emit()

    cartesian_pixel_size = property(_cartesian_pixel_size,
                                    _set_cartesian_pixel_size)

    def _cartesian_virtual_plane_distance(self):
        return self.config['image']['cartesian']['virtual_plane_distance']

    def set_cartesian_virtual_plane_distance(self, v):
        self.config['image']['cartesian']['virtual_plane_distance'] = v
        self.rerender_needed.emit()

    cartesian_virtual_plane_distance = property(
        _cartesian_virtual_plane_distance,
        set_cartesian_virtual_plane_distance)

    def _cartesian_plane_normal_rotate_x(self):
        return self.config['image']['cartesian']['plane_normal_rotate_x']

    def set_cartesian_plane_normal_rotate_x(self, v):
        self.config['image']['cartesian']['plane_normal_rotate_x'] = v
        self.rerender_needed.emit()

    cartesian_plane_normal_rotate_x = property(
        _cartesian_plane_normal_rotate_x,
        set_cartesian_plane_normal_rotate_x)

    def _cartesian_plane_normal_rotate_y(self):
        return self.config['image']['cartesian']['plane_normal_rotate_y']

    def set_cartesian_plane_normal_rotate_y(self, v):
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
        self.config['image']['show_detector_borders'] = v
        self.rerender_needed.emit()

    @property
    def colormap_min(self):
        return self.config['image']['colormap']['min']

    def set_colormap_min(self, v):
        self.config['image']['colormap']['min'] = v
