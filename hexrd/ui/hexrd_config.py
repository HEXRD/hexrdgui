import copy
import pickle

from PySide2.QtCore import QSettings

import fabio
import yaml

from hexrd.ui import resource_loader

import hexrd.ui.resources.calibration
import hexrd.ui.resources.materials


class Singleton(type):

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args,
                                                                 **kwargs)
        return cls._instances[cls]


# This is a singleton class that contains the configuration
class HexrdConfig(metaclass=Singleton):

    def __init__(self):
        """iconfig means instrument config"""
        self.iconfig = None
        self.default_iconfig = None
        self.gui_yaml_dict = None
        self.cached_gui_yaml_dicts = {}
        self.working_dir = None
        self.images_dir = None
        self.mconfig = {}
        self.images_dict = {}

        self.load_settings()

        self.load_default_mconfig()
        self.mconfig = self.default_mconfig

        # Load default configuration settings
        self.load_default_config()

        if self.iconfig is None:
            # Load the default iconfig settings
            self.iconfig = copy.deepcopy(self.default_iconfig)

        # Load the GUI to yaml maps
        self.load_gui_yaml_dict()

        # Load the default materials
        self.load_default_materials()

    def save_settings(self):
        settings = QSettings()
        settings.setValue('iconfig', self.iconfig)
        settings.setValue('images_dir', self.images_dir)

    def load_settings(self):
        settings = QSettings()
        self.iconfig = settings.value('iconfig', None)
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
        self.default_iconfig = yaml.load(text, Loader=yaml.FullLoader)

    def load_images(self, names, image_files):
        self.images_dict.clear()
        for name, f in zip(names, image_files):
            self.images_dict[name] = fabio.open(f).data

    def image(self, name):
        return self.images_dict.get(name)

    def images(self):
        return self.images_dict

    def load_iconfig(self, yml_file):
        with open(yml_file, 'r') as f:
            self.iconfig = yaml.load(f, Loader=yaml.FullLoader)

        return self.iconfig

    def save_iconfig(self, output_file):
        with open(output_file, 'w') as f:
            yaml.dump(self.iconfig, f)

    def _search_gui_yaml_dict(self, d, res, cur_path=None):
        """This recursive function gets all yaml paths to GUI variables

        res is a list of results that will contain a tuple of GUI
        variables to paths. The GUI variables are assumed to start
        with 'cal_' for calibration.

        For instance, it will contain
        ("cal_energy", [ "beam", "energy" ] ), which means that
        the path to the default value of "cal_energy" is
        self.iconfig["beam"]["energy"]
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
        self.iconfig["beam"]["energy"]
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

    def set_iconfig_val(self, path, value):
        """This sets a value from a path list."""
        cur_val = self.iconfig
        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            cur_val[path[-1]] = value
        except:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.iconfig))
            raise Exception(msg)

    def get_iconfig_val(self, path):
        """This obtains a dict value from a path list.

        For instance, if path is [ "beam", "energy" ], it will
        return self.iconfig["beam"]["energy"]

        """
        cur_val = self.iconfig
        try:
            for val in path:
                cur_val = cur_val[val]
        except:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.iconfig))
            raise Exception(msg)

        return cur_val

    def set_val_from_widget_name(self, widget_name, value, detector=None):
        yaml_paths = self.get_gui_yaml_paths()
        for var, path in yaml_paths:
            if var == widget_name:
                if 'detector_name' in path:
                    # Replace detector_name with the detector name
                    path[path.index('detector_name')] = detector

                self.set_iconfig_val(path, value)
                return

        raise Exception(widget_name + ' was not found in iconfig!')

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
        return list(self.iconfig.get('detectors', {}).keys())

    def get_default_detector(self):
        return copy.deepcopy(self.default_iconfig['detectors']['ge1'])

    def get_detector(self, detector_name):
        return self.iconfig['detectors'][detector_name]

    def add_detector(self, detector_name, detector_to_copy=None):
        if detector_to_copy is not None:
            new_detector = copy.deepcopy(self.get_detector(detector_to_copy))
        else:
            new_detector = self.get_default_detector()

        self.iconfig['detectors'][detector_name] = new_detector

    def remove_detector(self, detector_name):
        del self.iconfig['detectors'][detector_name]

    def rename_detector(self, old_name, new_name):
        if old_name != new_name:
            self.iconfig['detectors'][new_name] = (
                self.iconfig['detectors'][old_name])
            self.remove_detector(old_name)

    # This section is for materials configuration
    def load_default_materials(self):
        data = resource_loader.load_resource(hexrd.ui.resources.materials,
                                             'materials.hexrd', binary=True)

        matlist = pickle.loads(data, encoding='latin1')
        self.set_materials(dict(zip([i.name for i in matlist], matlist)))

    def load_default_mconfig(self):
        yml = resource_loader.load_resource(hexrd.ui.resources.materials,
                                            'materials_panel_defaults.yml')
        self.default_mconfig = yaml.load(yml, Loader=yaml.FullLoader)

    def set_materials(self, materials):
        self.mconfig['materials'] = materials

    def materials(self):
        return self.mconfig.get('materials', {})

    def material(self, name):
        return self.mconfig['materials'].get(name)

    def set_active_material(self, name):
        if name not in self.materials():
            raise Exception(name + ' was not found in materials list: ' +
                            str(self.materials()))

        self.mconfig['active_material'] = name

    def active_material_name(self):
        return self.mconfig.get('active_material')

    def active_material(self):
        m = self.active_material_name()
        return self.material(m)

    def set_selected_rings(self, rings):
        self.mconfig['selected_rings'] = rings

    def selected_rings(self):
        return self.mconfig.get('selected_rings')

    def set_show_rings(self, b):
        self.mconfig['show_rings'] = b

    def show_rings(self):
        return self.mconfig.get('show_rings')

    def set_show_ring_ranges(self, b):
        self.mconfig['show_ring_ranges'] = b

    def show_ring_ranges(self):
        return self.mconfig.get('show_ring_ranges')

    def set_ring_ranges(self, r):
        self.mconfig['ring_ranges'] = r

    def ring_ranges(self):
        return self.mconfig.get('ring_ranges')
