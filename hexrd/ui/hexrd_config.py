import copy
import pickle

from PySide2.QtCore import Signal, QObject, QSettings

import yaml

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

    def __init__(self):
        # Should this have a parent?
        super(HexrdConfig, self).__init__(None)
        self.config = {}
        self.default_config = {}
        self.gui_yaml_dict = None
        self.cached_gui_yaml_dicts = {}
        self.working_dir = None
        self.images_dir = None
        self.images_dict = {}
        self.imageseries_dict = {}
        self.hdf5_path = []
        self.live_update = False

        self.load_settings()

        # Load default configuration settings
        self.load_default_config()

        self.config['materials'] = copy.deepcopy(
            self.default_config['materials'])
        self.config['resolution'] = copy.deepcopy(
            self.default_config['resolution'])

        if self.config.get('instrument') is None:
            # Load the default config['instrument'] settings
            self.config['instrument'] = copy.deepcopy(
                self.default_config['instrument'])
            self.create_internal_config(self.config['instrument'])

        # Load the GUI to yaml maps
        self.load_gui_yaml_dict()

        # Load the default materials
        self.load_default_materials()

        self.update_active_material_energy()

    def save_settings(self):
        settings = QSettings()
        settings.setValue('config_instrument', self.config['instrument'])
        settings.setValue('images_dir', self.images_dir)
        settings.setValue('hdf5_path', self.hdf5_path)
        settings.setValue('live_update', self.live_update)

    def load_settings(self):
        settings = QSettings()
        self.config['instrument'] = settings.value('config_instrument', None)
        self.images_dir = settings.value('images_dir', None)
        self.hdf5_path = settings.value('hdf5_path', None)
        # All QSettings come back as strings.
        self.live_update = bool(settings.value('live_update', False) == 'true')
        if self.config.get('instrument') is not None:
            self.create_internal_config(self.config['instrument'])

    # This is here for backward compatibility
    @property
    def instrument_config(self):
        return self.filter_instrument_config(
            self.config['instrument'])

    @property
    def internal_instrument_config(self):
        return self.config['instrument']

    def set_images_dir(self, images_dir):
        self.images_dir = images_dir

    def load_gui_yaml_dict(self):
        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'yaml_to_gui.yml')
        self.gui_yaml_dict = yaml.load(text, Loader=yaml.FullLoader)

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
                                             'default_resolution_config.yml')
        self.default_config['resolution'] = yaml.load(text,
                                                      Loader=yaml.FullLoader)

    def image(self, name):
        return self.images_dict.get(name)

    def images(self):
        return self.images_dict

    def ims_image(self, name):
        return self.imageseries_dict.get(name)

    def imageseries(self):
        return self.imageseries_dict

    def load_instrument_config(self, yml_file):
        with open(yml_file, 'r') as f:
            self.config['instrument'] = yaml.load(f, Loader=yaml.FullLoader)
        self.create_internal_config(self.config['instrument'])

        self.update_active_material_energy()
        return self.config['instrument']

    def save_instrument_config(self, output_file):
        default = self.filter_instrument_config(self.config['instrument'])
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

    def remove_detector(self, detector_name):
        del self.config['instrument']['detectors'][detector_name]

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

        self.new_plane_data.emit()
        self.ring_config_changed.emit()

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
        self.ring_config_changed.emit()

    ring_ranges = property(_ring_ranges, _set_ring_ranges)

    def _polar_pixel_size_tth(self):
        return self.config['resolution']['polar']['pixel_size_tth']

    def _set_polar_pixel_size_tth(self, v):
        self.config['resolution']['polar']['pixel_size_tth'] = v

    polar_pixel_size_tth = property(_polar_pixel_size_tth,
                                    _set_polar_pixel_size_tth)

    def _polar_pixel_size_eta(self):
        return self.config['resolution']['polar']['pixel_size_eta']

    def _set_polar_pixel_size_eta(self, v):
        self.config['resolution']['polar']['pixel_size_eta'] = v

    polar_pixel_size_eta = property(_polar_pixel_size_eta,
                                    _set_polar_pixel_size_eta)

    def _cartesian_pixel_size(self):
        return self.config['resolution']['cartesian']['pixel_size']

    def _set_cartesian_pixel_size(self, v):
        self.config['resolution']['cartesian']['pixel_size'] = v

    cartesian_pixel_size = property(_cartesian_pixel_size,
                                    _set_cartesian_pixel_size)
