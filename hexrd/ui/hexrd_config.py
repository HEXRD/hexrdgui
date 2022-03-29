import copy
import logging
import os
from pathlib import Path
import sys

from PySide2.QtCore import Signal, QCoreApplication, QObject, QSettings, QTimer

import h5py
import numpy as np
import yaml

import hexrd.imageseries.save
from hexrd.config.loader import NumPyIncludeLoader
from hexrd.instrument import HEDMInstrument
from hexrd.material import load_materials_hdf5, save_materials_hdf5, Material
from hexrd.rotations import RotMatEuler
from hexrd.valunits import valWUnit

from hexrd.ui import constants
from hexrd.ui import overlays
from hexrd.ui import resource_loader
from hexrd.ui import utils
from hexrd.ui.singletons import QSingleton

import hexrd.ui.resources.calibration
import hexrd.ui.resources.indexing
import hexrd.ui.resources.materials


# This is a singleton class that contains the configuration
class HexrdConfig(QObject, metaclass=QSingleton):
    """The central configuration class for the program

    This class contains properties where possible, and it uses the
    following syntax for declaring them:

    name = property(_name, _set_name)

    This is done so that _set_name() may be connected to in Qt's signal
    and slot syntax.
    """

    """Emitted when new plane data is generated for the active material"""
    new_plane_data = Signal()

    """Emitted when an image view has finished loading

    The dict contains the images. This is used, for instance, to update
    the brightness and contrast histogram with the new image data.
    """
    image_view_loaded = Signal(dict)

    """Emitted when overlay configuration has changed"""
    overlay_config_changed = Signal()

    """Emitted when beam vector has changed"""
    beam_vector_changed = Signal()

    """Emitted when the oscillation stage changes"""
    oscillation_stage_changed = Signal()

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

    """Emitted when auto picked data needs to be re-rendered"""
    rerender_auto_picked_data = Signal()

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

    """Emitted when the materials dict is modified in any way"""
    materials_dict_modified = Signal()

    """Emitted when a material is renamed"""
    material_renamed = Signal()

    """Emitted when materials were added"""
    materials_added = Signal()

    """Emitted when materials were removed"""
    materials_removed = Signal()

    """Emitted when materials keys were re-arranged"""
    materials_rearranged = Signal()

    """Emitted when materials have been set"""
    materials_set = Signal()

    """Emitted to update the tth width in the powder overlay editor"""
    material_tth_width_modified = Signal(str)

    """Emitted when a new raw mask has been created"""
    raw_masks_changed = Signal()

    """Emitted when a new polar mask has been created"""
    polar_masks_changed = Signal()

    """Emitted when reflections tables for a given material should update

    The string argument is the material name.
    """
    update_reflections_tables = Signal(str)

    """Emitted when parts of the GUI should save their state in the file"""
    save_state = Signal(h5py.File)

    """Emitted when parts of the GUI should load their state from the file"""
    load_state = Signal(h5py.File)

    """Indicate that the state was loaded..."""
    state_loaded = Signal()

    """Indicate that the overlay editor should update its GUI"""
    update_overlay_editor = Signal()

    """Indicate that the beam marker has been modified"""
    beam_marker_modified = Signal()

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
        self.masks = {}
        self.raw_mask_coords = {}
        self.visible_masks = []
        self.backup_tth_maxes = {}
        self.overlays = []
        self.wppf_data = None
        self._auto_picked_data = None
        self.last_unscaled_azimuthal_integral_data = None
        self._threshold_data = {}
        self.stack_state = {}
        self.unaggregated_images = None
        self.llnl_boundary_positions = {}
        self.logging_stdout_handler = None
        self.logging_stderr_handler = None
        self.loading_state = False
        self.last_loaded_state_file = None
        self.find_orientations_grains_table = None
        self.fit_grains_grains_table = None
        self.hedm_calibration_output_grains_table = None

        self.setup_logging()

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
        self.load_default_material('CeO2')

        # Re-load the previous active material if available
        mat = self.previous_active_material
        if mat is not None and mat in self.materials:
            self.active_material = mat

        self.update_visible_material_energies()

        self.setup_connections()

    def setup_connections(self):
        materials_dict_modified_signals = [
            self.material_renamed,
            self.materials_added,
            self.materials_removed,
            self.materials_rearranged,
            self.materials_set,
        ]

        for signal in materials_dict_modified_signals:
            signal.connect(self.materials_dict_modified.emit)

    # Returns a list of tuples contain the names of attributes and their
    # default values that should be persisted as part of the configuration
    # state.
    def _attributes_to_persist(self):
        return [
            ('active_material_name', None),
            ('config_instrument', None),
            ('config_calibration', None),
            ('config_indexing', None),
            ('config_image', None),
            ('images_dir', None),
            ('working_dir', None),
            ('hdf5_path', None),
            ('live_update', True),
            ('euler_angle_convention',
                constants.DEFAULT_EULER_ANGLE_CONVENTION),
            ('collapsed_state', []),
            ('load_panel_state', {}),
            ('stack_state', {}),
            ('llnl_boundary_positions', {}),
            ('_imported_default_materials', []),
            ('overlays_dictified', []),
        ]

    # Provide a mapping from attribute names to the keys used in our state
    # file or QSettings. Its a one to one mapping appart from a few exceptions
    def _attribute_to_settings_key(self, attribute_name):
        exceptions = {
            'llnl_boundary_positions': 'boundary_positions',
            'stack_state': 'image_stack_state',
            'active_material_name': 'active_material',
            'overlays_dictified': 'overlays',
        }

        if attribute_name in exceptions:
            return exceptions[attribute_name]

        return attribute_name

    # Save the state in QSettings
    def _save_state_to_settings(self, state, settings):
        for name, value in state.items():
            settings.setValue(name, value)

    # Load the state from QSettings
    def _load_state_from_settings(self, settings):
        state = {}
        for name, default in self._attributes_to_persist():
            state[name] = settings.value(
                self._attribute_to_settings_key(name), default)

        return state

    def state_to_persist(self):
        """
        Return a dict of the parts of HexrdConfig that should persisted to
        preserve the state of the application.
        """
        state = {}
        for name, _ in self._attributes_to_persist():
            state[self._attribute_to_settings_key(name)] = getattr(self, name)

        state['euler_angle_convention'] = self.euler_angle_convention

        return state

    def load_from_state(self, state):
        """
        Update HexrdConfig using a loaded state.
        """

        # The "active_material_name" is a special case that will be set to
        # "previous_active_material".
        # We need to set euler_angle_convention and overlays in a special way
        skip = [
            'active_material_name',
            'euler_angle_convention',
            'overlays_dictified',
        ]

        if self.loading_state:
            # Do not load default materials if we are loading state
            skip.append('_imported_default_materials')

        try:
            for name, value in state.items():
                if name not in skip:
                    setattr(self, name, value)
        except AttributeError:
            raise AttributeError(f'Failed to set attribute {name}')

        # All QSettings come back as strings. So check that we are dealing with
        # a boolean and convert if necessary
        if not isinstance(self.live_update, bool):
            self.live_update = self.live_update == 'true'

        self.previous_active_material = state.get('active_material_name')

        # Re-load the previous active material if available
        mat = self.previous_active_material
        if mat is not None and mat in self.materials:
            self.active_material = mat

        # Read the attribute set by _load_attributes
        conv = state['euler_angle_convention']
        if isinstance(conv, tuple):
            # Convert to our new method of storing it
            conv = {'axes_order': conv[0], 'extrinsic': conv[1]}

        self.set_euler_angle_convention(conv, convert_config=False)

        def set_overlays():
            v = state.get('overlays_dictified')
            self.overlays_dictified = v if v is not None else {}

        if 'overlays_dictified' in state:
            # Powder overlays need a fully constructed HexrdConfig object
            # to set the refinements (because it needs to get the material)
            # Thus, set the overlays later.
            QTimer.singleShot(0, set_overlays)

    @property
    def _instrument_status_dict(self):
        config = self.internal_instrument_config

        def recurse(cur, result):
            for k, v in cur.items():
                if 'status' in v:
                    result[k] = v['status']
                else:
                    result[k] = {}
                    recurse(v, result[k])

        result = {}
        recurse(config, result)
        return result

    @_instrument_status_dict.setter
    def _instrument_status_dict(self, v):
        config = self.internal_instrument_config

        def recurse(cur, config):
            for k, v in cur.items():
                if k not in config:
                    continue

                if 'status' in config[k]:
                    config[k]['status'] = v
                else:
                    recurse(v, config[k])

        recurse(v, config)

    def save_settings(self):
        settings = QSettings()

        state = self.state_to_persist()
        self._save_state_to_settings(state, settings)

    def load_settings(self):
        settings = QSettings()

        state = self._load_state_from_settings(settings)
        self.load_from_state(state)

    @property
    def _imported_default_materials(self):
        material_names = list(self.materials)
        defaults = self.available_default_materials
        return [x for x in material_names if x in defaults]

    @_imported_default_materials.setter
    def _imported_default_materials(self, v):

        # A list with a single item will come back from QSettings as a str,
        # so make sure we convert it to a list.
        if isinstance(v, str):
            v = [v]

        for x in v:
            self.load_default_material(x)

    @property
    def overlays_dictified(self):
        return [overlays.to_dict(x) for x in self.overlays]

    @overlays_dictified.setter
    def overlays_dictified(self, v):
        material_names = list(self.materials)
        default_materials = self.available_default_materials

        self.overlays = []
        for overlay_dict in v:
            material_name = overlays.compatibility.material_name(overlay_dict)
            if material_name not in material_names:
                if material_name in default_materials:
                    # If this is a default material, try to load it
                    self.load_default_material(material_name)
                else:
                    # Skip over ones that do not have a matching material
                    continue

            self.overlays.append(overlays.from_dict(overlay_dict))

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

    @property
    def is_unary_imageseries(self):
        return self.imageseries_length == 1

    @property
    def imageseries_length(self):
        if not self.imageseries_dict:
            return 0

        # Assume all imageseries are the same length
        return len(next(iter(self.imageseries_dict.values())))

    @property
    def has_dummy_images(self):
        if not self.imageseries_dict:
            return False

        first_ims = next(iter(self.imageseries_dict.values()))
        return getattr(first_ims, 'is_dummy', False)

    @property
    def has_images(self):
        # There are images, and they are not dummy images
        return bool(self.imageseries_dict and not self.has_dummy_images)

    @property
    def omega_imageseries_dict(self):
        if self.is_aggregated:
            imsd = self.unagg_images
        else:
            imsd = self.imageseries_dict

        if not imsd:
            return None

        if any(not utils.is_omega_imageseries(ims) for ims in imsd.values()):
            # This is not an omega imageseries dict...
            return None

        return imsd

    @property
    def has_omegas(self):
        return self.omega_imageseries_dict is not None

    @property
    def omega_ranges(self):
        # Just assume all of the imageseries have the same omega ranges.
        # Grab the first one.
        imsd = self.omega_imageseries_dict
        if not imsd:
            return None

        first_ims = next(iter(imsd.values()))
        return first_ims.omega[self.current_imageseries_idx]

    @property
    def raw_images_dict(self):
        """Get a dict of images with the current index"""
        idx = self.current_imageseries_idx
        ret = {}
        for key in self.imageseries_dict.keys():
            ret[key] = self.image(key, idx)

        return ret

    @property
    def intensity_corrected_images_dict(self):
        """Performs intensity corrections, if any, before returning"""
        images_dict = self.raw_images_dict

        if not self.any_intensity_corrections:
            # No intensity corrections. Return.
            return images_dict

        # Some methods require an instrument. Go ahead and create one.
        from hexrd.ui.create_hedm_instrument import create_hedm_instrument
        instr = create_hedm_instrument()

        if HexrdConfig().apply_pixel_solid_angle_correction:
            for name, img in images_dict.items():
                panel = instr.detectors[name]
                images_dict[name] = img / panel.pixel_solid_angles

        if HexrdConfig().apply_polarization_correction:
            options = self.config['image']['polarization']
            kwargs = {
                'unpolarized': options['unpolarized'],
                'f_hor': options['f_hor'],
                'f_vert': options['f_vert'],
            }

            for name, img in images_dict.items():
                panel = instr.detectors[name]
                factor = panel.polarization_factor(**kwargs)
                images_dict[name] = img / factor

        if HexrdConfig().apply_lorentz_correction:
            for name, img in images_dict.items():
                panel = instr.detectors[name]
                factor = panel.lorentz_factor()
                images_dict[name] = img / factor

        if HexrdConfig().intensity_subtract_minimum:
            minimum = min([np.nanmin(x) for x in images_dict.values()])
            for name, img in images_dict.items():
                images_dict[name] = img - minimum

        return images_dict

    @property
    def images_dict(self):
        """Default to intensity corrected images dict"""
        return self.intensity_corrected_images_dict

    @property
    def raw_masks_dict(self):
        """Get a masks dict"""
        # We must ensure that we are using raw masks
        from hexrd.ui.create_raw_mask import rebuild_raw_masks
        prev_masks = copy.deepcopy(self.masks)
        try:
            rebuild_raw_masks()
            masks = copy.deepcopy(self.masks)
        finally:
            self.masks = prev_masks

        masks_dict = {}
        images_dict = self.images_dict
        for name, img in images_dict.items():
            final_mask = np.ones(img.shape, dtype=bool)
            for mask_name, data in masks.items():
                if mask_name not in self.visible_masks:
                    continue

                for det, mask in data:
                    if det == name:
                        final_mask = np.logical_and(final_mask, mask)
            masks_dict[name] = final_mask

        return masks_dict

    @property
    def masked_images_dict(self):
        """Get an images dict where masks have been applied"""
        images_dict = self.images_dict
        for det, mask in self.raw_masks_dict.items():
            for name, img in images_dict.items():
                if det == name:
                    img[~mask] = 0

        return images_dict

    def save_imageseries(self, ims, name, write_file, selected_format,
                         **kwargs):
        hexrd.imageseries.save.write(ims, write_file, selected_format,
                                     **kwargs)

    def clear_images(self, initial_load=False):
        self.reset_unagg_imgs()
        self.imageseries_dict.clear()
        if self.load_panel_state is not None and not initial_load:
            self.load_panel_state.clear()
            self.load_panel_state_reset.emit()

    def load_instrument_config(self, path, import_raw=False):
        old_detectors = self.detector_names

        rme = self.rotation_matrix_euler()

        def read_yaml():
            with open(path, 'r') as f:
                conf = yaml.load(f, Loader=NumPyIncludeLoader)

            instr = HEDMInstrument(conf, tilt_calibration_mapping=rme)
            return utils.instr_to_internal_dict(instr)

        def read_hexrd():
            def read_file(f):
                return HEDMInstrument(f, tilt_calibration_mapping=rme)

            if isinstance(path, h5py.File):
                instr = read_file(path)
            else:
                with h5py.File(path, 'r') as f:
                    instr = read_file(f)

            return utils.instr_to_internal_dict(instr)

        formats = {
            '.yml': read_yaml,
            '.hexrd': read_hexrd,
        }

        if isinstance(path, h5py.File):
            ext = '.hexrd'
        else:
            ext = Path(path).suffix

        if ext not in formats:
            raise Exception(f'Unknown extension: {ext}')

        self.config['instrument'] = formats[ext]()

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

        if not import_raw:
            self.instrument_config_loaded.emit()

        new_detectors = self.detector_names
        if old_detectors != new_detectors:
            self.detectors_changed.emit()
        else:
            # Still need a deep rerender
            self.deep_rerender_needed.emit()

        return self.config['instrument']

    def save_instrument_config(self, output_file):
        from hexrd.ui.create_hedm_instrument import create_hedm_instrument

        styles = {
            '.yml': 'yaml',
            '.hexrd': 'hdf5',
        }

        if isinstance(output_file, h5py.File):
            ext = '.hexrd'
        else:
            ext = Path(output_file).suffix
            if ext not in styles:
                raise Exception(f'Unknown output extension: {ext}')

        instr = create_hedm_instrument()
        instr.write_config(output_file, style=styles[ext])

    def load_materials(self, f):
        beam_energy = valWUnit('beam', 'energy', self.beam_energy, 'keV')
        self.materials = load_materials_hdf5(f, kev=beam_energy)

    def save_materials(self, f, path=None):
        save_materials_hdf5(f, self.materials, path)

    def import_material(self, f):
        beam_energy = valWUnit('beam', 'energy', self.beam_energy, 'keV')
        name = os.path.splitext(os.path.basename(f))[0]

        # Make sure we have a unique name
        name = utils.unique_name(self.materials, name)

        material = Material(name, f, kev=beam_energy)
        self.add_material(name, material)

        return name

    def save_indexing_config(self, output_file):
        cfg = {}

        def recursive_key_check(d, c):
            for k, v in d.items():
                if k.startswith('_'):
                    continue

                if isinstance(v, dict):
                    c[k] = {}
                    recursive_key_check(v, c[k])
                else:
                    c[k] = v

        recursive_key_check(self.indexing_config, cfg)

        current_material = self.indexing_config['_selected_material']
        selected_material = self.material(current_material)
        material = {
            'definitions': 'materials.h5',
            'active': current_material,
            'dmin': selected_material.dmin.getVal('angstrom'),
            'tth_width': selected_material.planeData.get_tThMax().item(),
            'min_sfac_ratio': None
        }

        data = []
        for det in self.detector_names:
            data.append({
                'file': f'{det}.h5',
                'args': {'path': 'imageseries'},
                'panel': det
            })

        image_series = {
            'format': 'hdf5',
            'data': data
        }

        omaps = self.indexing_config['find_orientations']['orientation_maps']
        active_hkls = omaps.get('_active_hkl_strings', None)
        seed_search = self.indexing_config['find_orientations']['seed_search']
        hkl_seeds = seed_search.get('_hkl_seed_strings', [])
        if active_hkls is None:
            cfg['find_orientations']['orientation_maps']['active_hkls'] = []
        else:
            curr_hkls = selected_material.planeData.getHKLs(asStr=True)
            hkls = [curr_hkls.index(x) for x in active_hkls if x in curr_hkls]
            seeds = [active_hkls.index(x) for x in hkl_seeds if x in curr_hkls]
            cfg['find_orientations']['orientation_maps']['active_hkls'] = hkls
            cfg['find_orientations']['orientation_maps']['file'] = None
            cfg['find_orientations']['seed_search']['hkl_seeds'] = seeds

        cfg['material'] = material
        cfg['instrument'] = 'instrument.yml'
        cfg['image_series'] = image_series
        cfg['working_dir'] = str(Path(output_file).parent)

        with open(output_file, 'w') as f:
            yaml.dump(cfg, f)

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
                if isinstance(value, (list, np.ndarray)):
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

        return np.asarray(statuses, dtype=bool)

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

        if path[0] == 'oscillation_stage':
            self.rerender_needed.emit()
            # Overlays need to update their instrument objects when
            # the oscillation stage changes.
            self.oscillation_stage_changed.emit()
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
                else:
                    chi_path = ['oscillation_stage', 'chi', 'value']
                    if path == chi_path:
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

    @property
    def available_default_materials(self):
        module = hexrd.ui.resources.materials
        with resource_loader.path(module, 'materials.h5') as file_path:
            with h5py.File(file_path) as f:
                return list(f.keys())

    # This section is for materials configuration
    def load_default_material(self, name):
        module = hexrd.ui.resources.materials
        materials = self.materials
        with resource_loader.path(module, 'materials.h5') as file_path:
            materials[name] = Material(name, file_path)

        self.materials = materials

        # Set the tth_max to match that of the polar resolution config.
        self.reset_tth_max(name)
        self.update_material_energy(materials[name])

    def add_material(self, name, material):
        self.add_materials([name], [material])

    def add_materials(self, names, materials):
        if any(x in self.materials for x in names):
            mats = list(self.materials.keys())
            msg = f'Some names {names} are already in materials list {mats}!'
            raise Exception(msg)

        if len(names) != len(materials):
            msg = f'{len(names)=} does not match {len(materials)=}!'
            raise Exception(msg)

        for name, mat in zip(names, materials):
            self.config['materials']['materials'][name] = mat
            # Force the material name to match
            mat.name = name
            self.reset_tth_max(name)

        self.materials_added.emit()

    def copy_materials(self, from_names, to_names):
        mats = self.materials
        cannot_copy = (
            any(x in from_names for x in to_names) or
            any(x in mats for x in to_names) or
            any(x not in mats for x in from_names) or
            len(from_names) != len(to_names)
        )
        if cannot_copy:
            mat_names = list(mats.keys())
            msg = f'Cannot copy {from_names=} to {to_names=} for {mat_names=}'
            raise Exception(msg)

        for from_name, to_name in zip(from_names, to_names):
            self.add_material(to_name, copy.deepcopy(mats[from_name]))

    def rearrange_materials(self, new_order):
        if sorted(new_order) != sorted(self.materials):
            old = list(self.materials.keys())
            msg = f'Cannot re-arrange material names from {old} to {new_order}'
            raise Exception(msg)

        mats = self.materials
        new_materials = {k: mats[k] for k in new_order}
        self.config['materials']['materials'] = new_materials

        # This should not require any overlay updates
        self.materials_rearranged.emit()

    def rename_material(self, old_name, new_name):
        if old_name == new_name:
            return

        ordering = list(self.materials.keys())
        ordering[ordering.index(old_name)] = new_name

        # First, rename the material
        self.materials[new_name] = self.materials[old_name]
        self.materials[new_name].name = new_name

        # Now re-create the dict to keep the ordering
        new_dict = {k: self.materials[k] for k in ordering}
        self.config['materials']['materials'] = new_dict

        # Rename any overlays as well
        for overlay in self.overlays:
            if overlay.material_name == old_name:
                overlay.material_name = new_name

        if self.active_material_name == old_name:
            # Set the dict directly to bypass the updates that occur
            # if we did self.active_material = new_name
            self.config['materials']['active_material'] = new_name

        self.material_renamed.emit()

    def modify_material(self, name, material):
        if name not in self.materials:
            raise Exception(name + ' is not in materials list!')
        self.config['materials']['materials'][name] = material

        self.flag_overlay_updates_for_material(name)
        self.overlay_config_changed.emit()

    def remove_material(self, name):
        self.remove_materials([name])

    def remove_materials(self, names):
        if any(x not in self.materials for x in names):
            mats = list(self.materials.keys())
            msg = f'Some of {names=} are not in materials list {mats=}'
            raise Exception(msg)

        for name in names:
            del self.config['materials']['materials'][name]

        self.prune_overlays()

        if self.active_material_name in names:
            if self.materials:
                self.active_material = next(iter(self.materials))
            else:
                self.active_material = None

        self.materials_removed.emit()

    def _materials(self):
        return self.config['materials'].get('materials', {})

    def _set_materials(self, materials):
        self.config['materials']['materials'] = materials
        if materials.keys():
            self.active_material = list(materials.keys())[0]

        self.prune_overlays()
        self.flag_overlay_updates_for_all_materials()
        self.overlay_config_changed.emit()

        self.materials_set.emit()

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

        return list({x.material_name for x in self.overlays if x.visible})

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
        self.overlays = [x for x in self.overlays if x.material_name in mats]
        self.overlay_config_changed.emit()

    def append_overlay(self, material_name, type):
        kwargs = {
            'material_name': material_name,
            'type': type,
        }
        overlay = overlays.create_overlay(**kwargs)
        self.overlays.append(overlay)
        self.overlay_config_changed.emit()

    def change_overlay_type(self, i, type):
        if not 0 <= i < len(self.overlays):
            # Out of range
            return

        overlay = self.overlays[i]
        if overlay.type == type:
            # No change needed
            return

        kwargs = {
            'material_name': overlay.material_name,
            'type': type,
        }
        new_overlay = overlays.create_overlay(**kwargs)
        new_overlay.instrument = self.overlays[i].instrument
        self.overlays[i] = new_overlay

    def clear_overlay_data(self):
        for overlay in self.overlays:
            overlay.update_needed = True

    def flag_overlay_updates_for_active_material(self):
        self.flag_overlay_updates_for_material(self.active_material_name)

    def flag_overlay_updates_for_material(self, material_name):
        for overlay in self.overlays:
            if overlay.material_name == material_name:
                overlay.update_needed = True

    def flag_overlay_updates_for_all_materials(self):
        for name in self.materials:
            self.flag_overlay_updates_for_material(name)

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

        # Update all overlays
        # The eta period is currently only affected by the min value
        self.flag_overlay_updates_for_all_materials()

        if not rerender:
            return

        self.rerender_needed.emit()
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

    def _polar_apply_erosion(self):
        return self.config['image']['polar']['apply_erosion']

    def set_polar_apply_erosion(self, v):
        self.config['image']['polar']['apply_erosion'] = v
        self.rerender_needed.emit()

    polar_apply_erosion = property(_polar_apply_erosion,
                                   set_polar_apply_erosion)

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

    def _apply_pixel_solid_angle_correction(self):
        return self.config['image']['apply_pixel_solid_angle_correction']

    def set_apply_pixel_solid_angle_correction(self, v):
        if v != self.apply_pixel_solid_angle_correction:
            self.config['image']['apply_pixel_solid_angle_correction'] = v
            self.deep_rerender_needed.emit()

    apply_pixel_solid_angle_correction = property(
        _apply_pixel_solid_angle_correction,
        set_apply_pixel_solid_angle_correction)

    @property
    def apply_polarization_correction(self):
        return self.config['image']['apply_polarization_correction']

    @apply_polarization_correction.setter
    def apply_polarization_correction(self, v):
        if v != self.apply_polarization_correction:
            self.config['image']['apply_polarization_correction'] = v
            self.deep_rerender_needed.emit()

    @property
    def apply_lorentz_correction(self):
        return self.config['image']['apply_lorentz_correction']

    @apply_lorentz_correction.setter
    def apply_lorentz_correction(self, v):
        if v != self.apply_lorentz_correction:
            self.config['image']['apply_lorentz_correction'] = v
            self.deep_rerender_needed.emit()

    def _intensity_subtract_minimum(self):
        return self.config['image']['intensity_subtract_minimum']

    def set_intensity_subtract_minimum(self, v):
        if v != self.intensity_subtract_minimum:
            self.config['image']['intensity_subtract_minimum'] = v
            self.deep_rerender_needed.emit()

    intensity_subtract_minimum = property(
        _intensity_subtract_minimum,
        set_intensity_subtract_minimum)

    @property
    def any_intensity_corrections(self):
        """Are we to perform any intensity corrections on the images?"""

        # Add to the list here as needed
        corrections = [
            'apply_pixel_solid_angle_correction',
            'apply_polarization_correction',
            'apply_lorentz_correction',
            'intensity_subtract_minimum',
        ]

        return any(getattr(self, x) for x in corrections)

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

    @property
    def show_beam_marker(self):
        return self.config['image']['show_beam_marker']

    @show_beam_marker.setter
    def show_beam_marker(self, v):
        if self.show_beam_marker != v:
            self.config['image']['show_beam_marker'] = v
            self.beam_marker_modified.emit()

    @property
    def beam_marker_style(self):
        return self.config['image']['beam_marker_style']

    @beam_marker_style.setter
    def beam_marker_style(self, v):
        if self.beam_marker_style != v:
            self.config['image']['beam_marker_style'] = v
            self.beam_marker_modified.emit()

    @staticmethod
    def num_distortion_parameters(func_name):
        if func_name == 'None':
            return 0
        elif func_name == 'GE_41RT':
            return 6
        elif func_name == 'Dexela_2923':
            return 8

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
    def unagg_images(self):
        img_dict = self.unaggregated_images
        if img_dict is None:
            img_dict = self.imageseries_dict
        return img_dict

    @property
    def is_aggregated(self):
        # Having unaggregated images implies the image series is aggregated
        return self.unaggregated_images is not None

    def reset_unagg_imgs(self, new_imgs=False):
        if not new_imgs:
            HexrdConfig().imageseries_dict = copy.copy(self.unagg_images)
        self.unaggregated_images = None

    def set_unagg_images(self):
        self.unaggregated_images = copy.copy(self.imageseries_dict)

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

    @property
    def wppf_plot_style(self):
        settings = HexrdConfig().config['calibration'].setdefault('wppf', {})
        settings = settings.setdefault('plot_style', {})
        if not settings:
            settings.update(copy.deepcopy(constants.DEFAULT_WPPF_PLOT_STYLE))
        return settings

    @wppf_plot_style.setter
    def wppf_plot_style(self, s):
        if self.wppf_plot_style != s:
            settings = HexrdConfig().config['calibration']['wppf']
            settings['plot_style'] = s
            self.rerender_wppf.emit()

    @property
    def auto_picked_data(self):
        return self._auto_picked_data

    @auto_picked_data.setter
    def auto_picked_data(self, data):
        self._auto_picked_data = data
        self.rerender_auto_picked_data.emit()

    def boundary_position(self, instrument, detector):
        det_bounds = self.llnl_boundary_positions.get(
            instrument, {}).get(detector, None)
        if not isinstance(det_bounds, dict):
            return None
        return det_bounds

    def set_boundary_position(self, instrument, detector, position):
        self.llnl_boundary_positions.setdefault(instrument, {})
        self.llnl_boundary_positions[instrument][detector] = position

    @property
    def logger(self):
        return logging.getLogger('hexrd')

    @property
    def logging_handlers(self):
        return (
            self.logging_stdout_handler,
            self.logging_stderr_handler,
        )

    def remove_logging_handlers(self):
        for handler in self.logging_handlers:
            if handler is None:
                continue

            handler.flush()
            handler.close()
            self.logger.removeHandler(handler)

        self.logging_stdout_handler = None
        self.logging_stderr_handler = None

    def setup_logging(self, log_level=logging.INFO):
        self.remove_logging_handlers()

        logger = self.logger
        logger.setLevel(log_level)

        log_format = ('%(message)s',)

        # Print INFO and DEBUG to stdout
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(logging.Formatter(*log_format))
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.addFilter(lambda r: r.levelno <= logging.INFO)
        logger.addHandler(stdout_handler)

        # Print all others to stderr
        stderr_handler = logging.StreamHandler(sys.stderr)
        stdout_handler.setFormatter(logging.Formatter(*log_format))
        stderr_handler.setLevel(logging.WARNING)
        logger.addHandler(stderr_handler)

        self.logging_stdout_handler = stdout_handler
        self.logging_stderr_handler = stderr_handler

    @property
    def logging_stdout_stream(self):
        if self.logging_stdout_handler is None:
            return None

        return self.logging_stdout_handler.stream

    @logging_stdout_stream.setter
    def logging_stdout_stream(self, v):
        if self.logging_stdout_handler is None:
            return

        self.logging_stdout_handler.setStream(v)

    @property
    def logging_stderr_stream(self):
        if self.logging_stderr_handler is None:
            return None

        return self.logging_stderr_handler.stream

    @logging_stderr_stream.setter
    def logging_stderr_stream(self, v):
        if self.logging_stderr_handler is None:
            return

        self.logging_stderr_handler.setStream(v)

    # Property with same name as settings key, used for persistence
    @property
    def config_instrument(self):
        return self.config['instrument']

    # Property with same name as settings key, used for persistence
    @config_instrument.setter
    def config_instrument(self, instrument):
        self.config['instrument'] = instrument

    # Property with same name as settings key, used for persistence
    @property
    def config_calibration(self):
        return self.config['calibration']

    # Property with same name as settings key, used for persistence
    @config_calibration.setter
    def config_calibration(self, calibration):
        self.config['calibration'] = calibration

    # Property with same name as settings key, used for persistence
    @property
    def config_indexing(self):
        return self.config['indexing']

    # Property with same name as settings key, used for persistence
    @config_indexing.setter
    def config_indexing(self, indexing):
        self.config['indexing'] = indexing

    # Property with same name as settings key, used for persistence
    @property
    def config_image(self):
        return self.config['image']

    # Property with same name as settings key, used for persistence
    @config_image.setter
    def config_image(self, image):
        self.config['image'] = image
