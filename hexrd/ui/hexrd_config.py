import copy
import pickle

from PySide2.QtCore import Signal, QObject, QSettings

import fabio
import yaml

from hexrd.ui import constants
from hexrd.ui import resource_loader

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

    def __init__(self):
        # Should this have a parent?
        super(HexrdConfig, self).__init__(None)
        self.instrument_config = None
        self.materials_config = None
        self.default_instrument_config = None
        self.default_materials_config = None
        self.gui_yaml_dict = None
        self.cached_gui_yaml_dicts = {}
        self.working_dir = None
        self.images_dir = None
        self.images_dict = {}

        self.load_settings()

        self.load_default_materials_config()
        self.materials_config = self.default_materials_config

        # Load default configuration settings
        self.load_default_config()

        if self.instrument_config is None:
            # Load the default instrument_config settings
            self.instrument_config = copy.deepcopy(
                self.default_instrument_config)

        # Load the GUI to yaml maps
        self.load_gui_yaml_dict()

        # Load the default materials
        self.load_default_materials()

        self.update_active_material_energy()

    def save_settings(self):
        settings = QSettings()
        settings.setValue('instrument_config', self.instrument_config)
        settings.setValue('images_dir', self.images_dir)

    def load_settings(self):
        settings = QSettings()
        self.instrument_config = settings.value('instrument_config', None)
        self.images_dir = settings.value('images_dir', None)

    def set_images_dir(self, images_dir):
        self.images_dir = images_dir

    def load_gui_yaml_dict(self):
        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'yaml_to_gui.yml')
        self.gui_yaml_dict = yaml.load(text, Loader=yaml.FullLoader)

    def load_default_config(self):
        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'defaults.yml')
        self.default_instrument_config = yaml.load(text,
                                                   Loader=yaml.FullLoader)

    def load_images(self, names, image_files):
        self.images_dict.clear()
        for name, f in zip(names, image_files):
            self.images_dict[name] = fabio.open(f).data

    def image(self, name):
        return self.images_dict.get(name)

    def images(self):
        return self.images_dict

    def load_instrument_config(self, yml_file):
        with open(yml_file, 'r') as f:
            self.instrument_config = yaml.load(f, Loader=yaml.FullLoader)

        self.update_active_material_energy()
        return self.instrument_config

    def save_instrument_config(self, output_file):
        with open(output_file, 'w') as f:
            yaml.dump(self.instrument_config, f)

    def _search_gui_yaml_dict(self, d, res, cur_path=None):
        """This recursive function gets all yaml paths to GUI variables

        res is a list of results that will contain a tuple of GUI
        variables to paths. The GUI variables are assumed to start
        with 'cal_' for calibration.

        For instance, it will contain
        ("cal_energy", [ "beam", "energy" ] ), which means that
        the path to the default value of "cal_energy" is
        self.instrument_config["beam"]["energy"]
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
                        res.append((element, cur_path + [key, i]))
            else:
                if isinstance(value, str) and value.startswith('cal_'):
                    res.append((value, cur_path + [key]))

    def get_gui_yaml_paths(self, path=None):
        """This returns all GUI variables along with their paths

        It assumes that all GUI variables start with 'cal_' for
        calibration.

        If the path argument is passed as well, it will only search
        the subset of the dictionary for GUI variables.

        For instance, the returned list may contain
        ("cal_energy", [ "beam", "energy" ] ), which means that
        the path to the default value of "cal_energy" is
        self.instrument_config["beam"]["energy"]
        """
        search_dict = self.gui_yaml_dict
        if path is not None:
            for item in path:
                search_dict = search_dict[item]
        else:
            path = []

        string_path = str(path)
        if string_path in self.cached_gui_yaml_dicts.keys():
            return self.cached_gui_yaml_dicts[string_path]

        res = []
        self._search_gui_yaml_dict(search_dict, res)
        self.cached_gui_yaml_dicts[string_path] = res
        return res

    def set_instrument_config_val(self, path, value):
        """This sets a value from a path list."""
        cur_val = self.instrument_config
        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            cur_val[path[-1]] = value
        except:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.instrument_config))
            raise Exception(msg)

        # If the beam energy was modified, update the active material
        if path == ['beam', 'energy']:
            self.update_active_material_energy()

    def get_instrument_config_val(self, path):
        """This obtains a dict value from a path list.

        For instance, if path is [ "beam", "energy" ], it will
        return self.instrument_config["beam"]["energy"]

        """
        cur_val = self.instrument_config
        try:
            for val in path:
                cur_val = cur_val[val]
        except:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.instrument_config))
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
        return list(self.instrument_config.get('detectors', {}).keys())

    def get_default_detector(self):
        return copy.deepcopy(
            self.default_instrument_config['detectors']['ge1'])

    def get_detector(self, detector_name):
        return self.instrument_config['detectors'][detector_name]

    def add_detector(self, detector_name, detector_to_copy=None):
        if detector_to_copy is not None:
            new_detector = copy.deepcopy(self.get_detector(detector_to_copy))
        else:
            new_detector = self.get_default_detector()

        self.instrument_config['detectors'][detector_name] = new_detector

    def remove_detector(self, detector_name):
        del self.instrument_config['detectors'][detector_name]

    def rename_detector(self, old_name, new_name):
        if old_name != new_name:
            self.instrument_config['detectors'][new_name] = (
                self.instrument_config['detectors'][old_name])
            self.remove_detector(old_name)

    # This section is for materials configuration
    def load_default_materials(self):
        data = resource_loader.load_resource(hexrd.ui.resources.materials,
                                             'materials.hexrd', binary=True)

        matlist = pickle.loads(data, encoding='latin1')
        materials = dict(zip([i.name for i in matlist], matlist))

        # For some reason, the default materials do not have the same beam
        # energy as their plane data. We need to fix this.
        for material in materials.values():
            pd_wavelength = material.planeData.get_wavelength()
            material._beamEnergy = constants.WAVELENGTH_TO_KEV / pd_wavelength

        self.materials = materials

    def load_default_materials_config(self):
        yml = resource_loader.load_resource(hexrd.ui.resources.materials,
                                            'materials_panel_defaults.yml')
        self.default_materials_config = yaml.load(yml, Loader=yaml.FullLoader)

    def add_material(self, name, material):
        if name in self.materials:
            raise Exception(name + ' is already in materials list!')
        self.materials_config['materials'][name] = material

    def rename_material(self, old_name, new_name):
        if old_name != new_name:
            self.materials_config['materials'][new_name] = (
                self.materials_config['materials'][old_name])

            if self.active_material_name() == old_name:
                # Change the active material before removing the old one
                self.active_material = new_name

            self.remove_material(old_name)

    def modify_material(self, name, material):
        if name not in self.materials:
            raise Exception(name + ' is not in materials list!')
        self.materials_config['materials'][name] = material

    def remove_material(self, name):
        if name not in self.materials:
            raise Exception(name + ' is not in materials list!')
        del self.materials_config['materials'][name]

        if name == self.active_material_name():
            if self.materials.keys():
                self.active_material = list(self.materials.keys())[0]
            else:
                self.active_material = None

    def _materials(self):
        return self.materials_config.get('materials', {})

    def _set_materials(self, materials):
        self.materials_config['materials'] = materials

    materials = property(_materials, _set_materials)

    def material(self, name):
        return self.materials_config['materials'].get(name)

    def _active_material(self):
        m = self.active_material_name()
        return self.material(m)

    def _set_active_material(self, name):
        if name not in self.materials and name is not None:
            raise Exception(name + ' was not found in materials list: ' +
                            str(self.materials))

        self.materials_config['active_material'] = name
        self.update_active_material_energy()

    active_material = property(_active_material, _set_active_material)

    def active_material_name(self):
        return self.materials_config.get('active_material')

    def update_active_material_energy(self):
        # This is a potentially expensive operation...
        energy = self.instrument_config.get('beam', {}).get('energy')
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
        mat._newPdata()

        self.new_plane_data.emit()

    def _selected_rings(self):
        return self.materials_config.get('selected_rings')

    def _set_selected_rings(self, rings):
        self.materials_config['selected_rings'] = rings

    selected_rings = property(_selected_rings, _set_selected_rings)

    def _show_rings(self):
        return self.materials_config.get('show_rings')

    def _set_show_rings(self, b):
        self.materials_config['show_rings'] = b

    show_rings = property(_show_rings, _set_show_rings)

    def _show_ring_ranges(self):
        return self.materials_config.get('show_ring_ranges')

    def _set_show_ring_ranges(self, b):
        self.materials_config['show_ring_ranges'] = b

    show_ring_ranges = property(_show_ring_ranges, _set_show_ring_ranges)

    def _ring_ranges(self):
        return self.materials_config.get('ring_ranges')

    def _set_ring_ranges(self, r):
        self.materials_config['ring_ranges'] = r

    ring_ranges = property(_ring_ranges, _set_ring_ranges)
