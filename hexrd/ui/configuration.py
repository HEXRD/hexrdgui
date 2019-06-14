import copy
import pickle

import yaml

from hexrd.ui import resource_loader

import hexrd.ui.resources.calibration
import hexrd.ui.resources.materials

class Configuration:

    def __init__(self, initial_config=None):
        self.config = None
        self.default_config = None
        self.gui_yaml_dict = None
        self.cached_gui_yaml_dicts = {}
        self.working_dir = None
        self.materials = None
        self.active_material = None

        # Load default configuration settings
        self.load_default_config()

        if initial_config is not None:
            self.config = initial_config
        else:
            # Load the default config settings
            self.config = copy.deepcopy(self.default_config)

        # Load the GUI to yaml maps
        self.load_gui_yaml_dict()

        # Load the default materials
        self.load_default_materials()

    def load_gui_yaml_dict(self):
        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'yaml_to_gui.yml')
        self.gui_yaml_dict = yaml.load(text, Loader=yaml.FullLoader)

    def load_default_config(self):
        text = resource_loader.load_resource(hexrd.ui.resources.calibration,
                                             'defaults.yml')
        self.default_config = yaml.load(text, Loader=yaml.FullLoader)

    def load_default_materials(self):
        data = resource_loader.load_resource(hexrd.ui.resources.materials,
                                             'materials.hexrd', binary=True)

        matlist = pickle.loads(data, encoding='latin1')
        self.materials = dict(zip([i.name for i in matlist], matlist))

        self.set_active_material('ceo2')

    def get_material(self, name):
        return self.materials.get(name)

    def set_active_material(self, name):
        if name not in self.materials:
            raise Exception(name + ' was not found in materials list: ' +
                            str(self.materials.keys()))

        self.active_material = name

    def get_active_material(self):
        return self.get_material(self.active_material)

    def load_config(self, yml_file):
        with open(yml_file, 'r') as f:
            self.config = yaml.load(f, Loader=yaml.FullLoader)

        return self.config

    def save_config(self, output_file):
        with open(output_file, 'w') as f:
            yaml.dump(self.config, f)

    def _search_gui_yaml_dict(self, d, res, cur_path=None):
        """This recursive function gets all yaml paths to GUI variables

        res is a list of results that will contain a tuple of GUI
        variables to paths. The GUI variables are assumed to start
        with 'cal_' for calibration.

        For instance, it will contain
        ("cal_energy", [ "beam", "energy" ] ), which means that
        the path to the default value of "cal_energy" is
        self.config["beam"]["energy"]
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
        self.config["beam"]["energy"]
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

    def set_config_val(self, path, value):
        """This sets a value from a path list."""
        cur_val = self.config
        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            cur_val[path[-1]] = value
        except:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.config))
            raise Exception(msg)

    def get_config_val(self, path):
        """This obtains a dict value from a path list.

        For instance, if path is [ "beam", "energy" ], it will
        return self.config["beam"]["energy"]

        """
        cur_val = self.config
        try:
            for val in path:
                cur_val = cur_val[val]
        except:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.config))
            raise Exception(msg)

        return cur_val

    def set_val_from_widget_name(self, widget_name, value, detector=None):
        yaml_paths = self.get_gui_yaml_paths()
        for var, path in yaml_paths:
            if var == widget_name:
                if 'detector_name' in path:
                    # Replace detector_name with the detector name
                    path[path.index('detector_name')] = detector

                self.set_config_val(path, value)
                return

        raise Exception(widget_name + ' was not found in config!')

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
        return list(self.config.get('detectors', {}).keys())

    def get_default_detector(self):
        return copy.deepcopy(self.default_config['detectors']['ge1'])

    def get_detector(self, detector_name):
        return self.config['detectors'][detector_name]

    def add_detector(self, detector_name, detector_to_copy=None):
        if detector_to_copy is not None:
            new_detector = copy.deepcopy(self.get_detector(detector_to_copy))
        else:
            new_detector = self.get_default_detector()

        self.config['detectors'][detector_name] = new_detector

    def remove_detector(self, detector_name):
        del self.config['detectors'][detector_name]

    def rename_detector(self, old_name, new_name):
        if old_name != new_name:
            self.config['detectors'][new_name] = self.config['detectors'][old_name]
            self.remove_detector(old_name)
