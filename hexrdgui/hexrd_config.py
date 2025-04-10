import copy
import logging
import os
from pathlib import Path
import sys

from PySide6.QtCore import Signal, QCoreApplication, QObject, QSettings, QTimer

import h5py
import matplotlib
import numpy as np
from scipy.signal import medfilt2d
import yaml

import hexrd.imageseries.save
from hexrd.config.loader import NumPyIncludeLoader
from hexrd.instrument import HEDMInstrument
from hexrd.instrument.constants import PHYSICS_PACKAGE_DEFAULTS, PINHOLE_DEFAULTS
from hexrd.instrument.physics_package import HEDPhysicsPackage
from hexrd.material import load_materials_hdf5, save_materials_hdf5, Material
from hexrd.rotations import RotMatEuler
from hexrd.utils.decorators import memoize
from hexrd.utils.yaml import NumpyToNativeDumper
from hexrd.valunits import valWUnit

from hexrdgui import constants
from hexrdgui import overlays
from hexrdgui import resource_loader
from hexrdgui import utils
from hexrdgui.masking.constants import MaskType
from hexrdgui.singletons import QSingleton

import hexrdgui.resources.calibration
import hexrdgui.resources.indexing
import hexrdgui.resources.materials


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

    """Emitted when polar masks have been re-applied.

    This might be needed to update the brightness and contract histogram
    with the new image data.
    """
    polar_masks_reapplied = Signal(np.ndarray)

    """Emitted when overlay configuration has changed"""
    overlay_config_changed = Signal()

    """Emitted when the beam energy was modified"""
    beam_energy_modified = Signal()

    """Emitted when beam vector has changed"""
    beam_vector_changed = Signal()

    """Emitted when the active beam has switched"""
    active_beam_switched = Signal()

    """Emitted when the oscillation stage changes"""
    oscillation_stage_changed = Signal()

    """Emitted when a panel's distortion is modified

    The key is the name of the panel that was modified
    """
    panel_distortion_modified = Signal(str)

    """Emitted when the option to show the saturation level is changed"""
    show_saturation_level_changed = Signal()

    """Emitted when the option to show the stereo border is changed"""
    show_stereo_border_changed = Signal()

    """Emitted when the option to tab images is changed"""
    tab_images_changed = Signal()

    """Emitted when a detector transforms are modified

    The list is a list of detectors which were modified.
    """
    detector_transforms_modified = Signal(list)

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

    """Emitted when a detector's shape changes

    The argument is the name of the detector whose shape changed.
    """
    detector_shape_changed = Signal(str)

    """Emitted when an instrument config has been loaded

    Warning: this will cause cartesian and polar parameters to be
    automatically regenerated, which are time consuming functions.
    """
    instrument_config_loaded = Signal()

    """Convenience signal to update the main window's status bar

    Arguments are: message (str)

    """
    update_status_bar = Signal(str)

    """Emitted when the load_panel_state has been modified"""
    load_panel_state_modified = Signal()

    """Emitted when the Euler angle convention changes"""
    euler_angle_convention_changed = Signal()

    """Emitted when the active material is changed to a different material"""
    active_material_changed = Signal()

    """Emitted when the materials panel should update"""
    active_material_modified = Signal()

    """Emitted when the materials dict is modified in any way"""
    materials_dict_modified = Signal()

    """Emitted when a material is renamed

    First argument is the old name, and second argument is the new name
    """
    material_renamed = Signal(str, str)

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

    """Emitted when the polar x-axis type changes"""
    polar_x_axis_type_changed = Signal()

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

    """Indicate that the overlay manager should update its table"""
    update_overlay_manager = Signal()

    """Indicate that the overlay editor should update its GUI"""
    update_overlay_editor = Signal()

    """Indicate that the main window should update it's instrument toolbox"""
    update_instrument_toolbox = Signal()

    """Indicate that the beam marker has been modified"""
    beam_marker_modified = Signal()

    """Emitted when an overlay's distortions have been modified.

    The argument is the name of the overlay that was modified.
    """
    overlay_distortions_modified = Signal(str)

    """Emitted when the tth distortion overlay is changed"""
    polar_tth_distortion_overlay_changed = Signal()

    """Emitted when an overlay's name has been changed

    The arguments are the old_name and the new_name
    """
    overlay_renamed = Signal(str, str)

    """Emitted when overlays were added, removed, or upon type change"""
    overlay_list_modified = Signal()

    """Emitted when the sample tilt is modified"""
    sample_tilt_modified = Signal()

    """Emitted when the loaded images change"""
    recent_images_changed = Signal()

    """Emitted when an azimuthal overlay gets modified"""
    azimuthal_options_modified = Signal()

    """Emitted when an azimuthal overlay gets modified"""
    azimuthal_plot_save_requested = Signal()

    """Emitted when material parameters are modified"""
    material_modified = Signal(str)

    """Emitted when the active canvas is changed"""
    active_canvas_changed = Signal()

    """Emitted when image mode widget should be enabled/disabled"""
    enable_image_mode_widget = Signal(bool)

    """Emitted with the navigation toolbar should be enabled/disabled"""
    enable_canvas_toolbar = Signal(bool)

    """Emitted when image mode widget needs to be in a certain mode"""
    set_image_mode_widget_tab = Signal(str)

    """Emitted when the image mode changed"""
    image_mode_changed = Signal(str)

    """Emitted when the physics package was modified"""
    physics_package_modified = Signal()

    """Emitted when canvas focus mode should be started/stopped

    In canvas focus mode, the following widgets in the main window are
    disabled:

    1. The image mode widget
    2. The config toolbox (material config and instrument config)
    3. The main window menu bar
    """
    enable_canvas_focus_mode = Signal(bool)

    def __init__(self):
        # Should this have a parent?
        super().__init__(None)
        self.config = {}
        self.default_config = {}
        self.gui_yaml_dict = None
        self.cached_gui_yaml_dicts = {}
        self.working_dir = '.'
        self.images_dir = None
        self.imageseries_dict = {}
        self.current_imageseries_idx = 0
        self.hdf5_path = []
        self.live_update = True
        self._show_saturation_level = False
        self._stitch_raw_roi_images = False
        self._tab_images = False
        self.previous_active_material = None
        self.collapsed_state = []
        self.load_panel_state = {}
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
        self._polar_tth_distortion_overlay_name = None
        self._custom_polar_tth_distortion_object = None
        self.saved_custom_polar_tth_distortion_object = None
        self.polar_corr_field_polar = None
        self.polar_angular_grid = None
        self._recent_images = {}
        self.max_cpus = None
        self.azimuthal_overlays = []
        self.azimuthal_offset = 0.
        self._active_beam_name = None
        self.show_azimuthal_legend = True
        self.show_all_colormaps = False
        self.limited_cmaps_list = constants.DEFAULT_LIMITED_CMAPS
        self.default_cmap = constants.DEFAULT_CMAP
        self._previous_structureless_calibration_picks_data = None
        self._image_mode = constants.ViewType.raw
        self._active_canvas = None
        self._sample_tilt = np.asarray([0, 0, 0], float)
        self.recent_state_files = []
        self._apply_absorption_correction = False
        self._physics_package = None
        self._detector_coatings = {}
        self._instrument_rigid_body_params = {}
        self._median_filter_correction = {}

        # Make sure that the matplotlib font size matches the application
        self.font_size = self.font_size

        self.setup_logging()

        default_conv = constants.DEFAULT_EULER_ANGLE_CONVENTION
        self.set_euler_angle_convention(default_conv, convert_config=False)

        # Load default configuration settings
        self.load_default_config()

        self.config['materials'] = copy.deepcopy(
            self.default_config['materials'])

        # We can't use the parsed args yet for this since this is in the
        # __init__ method. So just check for this flag manually.
        if '--ignore-settings' not in QCoreApplication.arguments():
            self.load_settings()

        self.set_defaults_if_missing()

        # Remove any 'None' distortion dicts from the detectors
        utils.remove_none_distortions(self.config['instrument'])

        # Save a backup of the previous config for later
        self.backup_instrument_config()

        # Load the GUI to yaml maps
        self.load_gui_yaml_dict()

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
            # Ignore all arguments when emitting that the materials dict was
            # modified.
            signal.connect(lambda *args: self.materials_dict_modified.emit())

        self.overlay_renamed.connect(self.on_overlay_renamed)
        self.material_modified.connect(self.check_active_material_changed)
        self.beam_energy_modified.connect(
            self.update_visible_material_energies)

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
            ('_stitch_raw_roi_images', False),
            ('font_size', 11),
            ('images_dir', None),
            ('working_dir', '.'),
            ('hdf5_path', []),
            ('live_update', True),
            ('euler_angle_convention',
                constants.DEFAULT_EULER_ANGLE_CONVENTION),
            ('collapsed_state', []),
            ('load_panel_state', {}),
            ('stack_state', {}),
            ('llnl_boundary_positions', {}),
            ('_imported_default_materials', []),
            ('_polar_tth_distortion_overlay_name', None),
            ('_recent_images', {}),
            ('azimuthal_overlays', []),
            ('show_azimuthal_legend', True),
            ('show_all_colormaps', False),
            ('limited_cmaps_list', constants.DEFAULT_LIMITED_CMAPS),
            ('default_cmap', constants.DEFAULT_CMAP),
            ('_previous_structureless_calibration_picks_data', None),
            ('sample_tilt', [0, 0, 0]),
            ('azimuthal_offset', 0.0),
            ('_active_beam_name', None),
            ('_instrument_rigid_body_params', {}),
            ('recent_state_files', []),
            ('apply_absorption_correction', False),
            ('physics_package_dictified', None),
            ('custom_polar_tth_distortion_object_serialized', None),
            ('detector_coatings_dictified', {}),
            ('overlays_dictified', []),
            ('apply_median_filter_correction', False),
            ('median_filter_kernel_size', 7),
        ]

    # Provide a mapping from attribute names to the keys used in our state
    # file or QSettings. Its a one to one mapping appart from a few exceptions
    def _attribute_to_settings_key(self, attribute_name):
        exceptions = {
            'llnl_boundary_positions': 'boundary_positions',
            'stack_state': 'image_stack_state',
            'active_material_name': 'active_material',
            'overlays_dictified': 'overlays',
            'physics_package_dictified': 'physics_package',
            'detector_coatings_dictified': '_detector_coatings'
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
        # Skip these when loading the QSettings.
        # These need to be saved in state files, but we do not want them
        # to persist in between regular sessions.
        skip = [
            'azimuthal_overlays',
            'azimuthal_offset',
            '_recent_images',
            '_instrument_rigid_body_params',
            '_polar_tth_distortion_overlay_name',
            'custom_polar_tth_distortion_object_serialized',
            'physics_package_dictified',
            'detector_coatings_dictified',
            'apply_median_filter_correction',
            'median_filter_kernel_size'
        ]

        state = {}
        for name, default in self._attributes_to_persist():
            if name in skip:
                continue

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

        return state

    def load_from_state(self, state):
        """
        Update HexrdConfig using a loaded state.
        """
        skip = [
            # The "active_material_name" is a special case that will be set to
            # "previous_active_material".
            'active_material_name',
            # We need to set euler_angle_convention and overlays in a special way
            'euler_angle_convention',
            'overlays_dictified',
            'physics_package_dictified',
            'detector_coatings_dictified',
        ]

        if self.loading_state:
            skip += [
                'config_instrument',
                # Do not load default materials if we are loading state
                '_imported_default_materials',
                # Skip colormap settings
                'show_all_colormaps',
                'limited_cmaps_list',
                'default_cmap',
                # Ignore the font size when loading from state
                'font_size',
                # Ignore recent state files when loading from state
                'recent_state_files',
            ]

        # Set the config first, if present
        if 'config_instrument' in state:
            self.config_instrument = state['config_instrument']
            if isinstance(self.beam_energy, dict):
                # We loaded a state with the old statuses. Remove them.
                self.remove_status(self.config['instrument'])

        # Now load everything else
        try:
            for name, value in state.items():
                if name not in skip:
                    setattr(self, name, value)
        except AttributeError:
            raise AttributeError(f'Failed to set attribute {name}')

        pinhole_settings = self.config['image'].get('pinhole_mask_settings', {})
        if 'pinhole_radius' in pinhole_settings:
            # We store this as diameter now
            pinhole_settings['pinhole_diameter'] = (
                pinhole_settings.pop('pinhole_radius') * 2
            )

        if self.cartesian_virtual_plane_distance < 0:
            # We used to allow this to be negative, but now must be positive.
            # Taking the absolute value should correct this adequately.
            self.cartesian_virtual_plane_distance = abs(
                self.cartesian_virtual_plane_distance)

        # All QSettings come back as strings. So check that we are dealing with
        # a boolean and convert if necessary
        if not isinstance(self.live_update, bool):
            self.live_update = self.live_update == 'true'
        if not isinstance(self.show_azimuthal_legend, bool):
            self.show_azimuthal_legend = self.show_azimuthal_legend == 'true'
        if not isinstance(self.show_all_colormaps, bool):
            self.show_all_colormaps = self.show_all_colormaps == 'true'
        if not isinstance(self.apply_absorption_correction, bool):
            self.apply_absorption_correction = self.apply_absorption_correction == 'true'
        if not isinstance(self.apply_median_filter_correction, bool):
            self.apply_median_filter_correction = self.apply_median_filter_correction == 'true'

        # This is None sometimes. Make sure it is an empty list instead.
        if self.recent_state_files is None:
            self.recent_state_files = []

        # A list with a single item will come back from QSettings as a str,
        # so make sure we convert it to a list.
        if not isinstance(self.recent_state_files, list):
            self.recent_state_files = [self.recent_state_files]

        if self.azimuthal_overlays is None:
            self.azimuthal_overlays = []

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

        if '_recent_images' not in state:
            self._recent_images.clear()

        def set_physics_and_coatings():
            pp = state.get('physics_package_dictified', None)
            self.physics_package_dictified = pp if pp is not None else {}
            dc = state.get('detector_coatings_dictified', None)
            self.detector_coatings_dictified = dc if dc is not None else {}

        if 'detector_coatings_dictified' in state:
            # Physics package and detector coatings need a fully constructed
            # HexrdConfig object to set their values because they need the
            # correct detector names. Set the objects later.
            QTimer.singleShot(0, set_physics_and_coatings)

        self.recent_images_changed.emit()

    @property
    def _q_settings_version(self):
        # Keep track of a QSettings version so we can ignore versions
        # that we might not be able to load.
        return 1

    def save_settings(self):
        settings = QSettings()
        settings.setValue('settings_version', self._q_settings_version)

        state = self.state_to_persist()
        self._save_state_to_settings(state, settings)

    def load_settings(self):
        settings = QSettings()
        current_version = int(settings.value('settings_version', -1))
        if current_version != self._q_settings_version:
            # The QSettings version is different (probably PySide6 is
            # trying to load a PySide2 QSettings, which has issues)
            # Ignore the settings, as there may be compatibility issues.
            return

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

            if overlay_dict.get('tth_distortion_type') is not None:
                if not self.has_physics_package:
                    # We need to create a default physics package
                    # This is for backward compatibility
                    self.create_default_physics_package()

            self.update_material_energy(self.materials[material_name])
            self.overlays.append(overlays.from_dict(overlay_dict))

        self.overlay_list_modified.emit()

    def emit_update_status_bar(self, msg):
        """Convenience signal to update the main window's status bar"""
        self.update_status_bar.emit(msg)

    @property
    def indexing_config(self):
        return self.config['indexing']

    # This is here for backward compatibility
    @property
    def instrument_config(self):
        return self.config_instrument

    @property
    def internal_instrument_config(self):
        return self.config_instrument

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

    def set_images_dir(self, images_dir):
        self.images_dir = images_dir

    def load_gui_yaml_dict(self):
        text = resource_loader.load_resource(hexrdgui.resources.calibration,
                                             'yaml_to_gui.yml')
        self.gui_yaml_dict = yaml.load(text, Loader=yaml.FullLoader)

    def load_default_config(self):
        text = resource_loader.load_resource(hexrdgui.resources.calibration,
                                             'default_instrument_config.yml')
        self.default_config['instrument'] = yaml.load(text,
                                                      Loader=yaml.FullLoader)

        text = resource_loader.load_resource(hexrdgui.resources.indexing,
                                             'default_indexing_config.yml')
        self.default_config['indexing'] = yaml.load(text,
                                                    Loader=yaml.FullLoader)

        yml = resource_loader.load_resource(hexrdgui.resources.materials,
                                            'materials_panel_defaults.yml')
        self.default_config['materials'] = yaml.load(yml,
                                                     Loader=yaml.FullLoader)

        text = resource_loader.load_resource(hexrdgui.resources.calibration,
                                             'default_image_config.yml')
        self.default_config['image'] = yaml.load(text, Loader=yaml.FullLoader)

        text = resource_loader.load_resource(hexrdgui.resources.calibration,
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

        self.set_beam_defaults_if_missing()
        self.set_detector_defaults_if_missing()

    def set_beam_defaults_if_missing(self):
        # Set beam defaults, including support for multi-xrs
        beam = self.config['instrument'].setdefault('beam', {})
        default_beam = self.default_config['instrument']['beam']
        f = self._recursive_set_defaults
        if beam and 'energy' not in beam:
            # Multi XRS. Set the default beam settings for each XRS.
            for settings in beam.values():
                f(settings, default_beam)
            return

        f(beam, default_beam)

    def set_detector_defaults_if_missing(self):
        # Find missing keys under detectors and set defaults for them
        default = self.default_detector
        for name in self.detector_names:
            self._recursive_set_defaults(self.detector(name), default)

    def _recursive_set_defaults(self, current, default):
        for key in default.keys():
            current.setdefault(key, copy.deepcopy(default[key]))

            if key in ('beam', 'detectors'):
                # Skip these defaults
                continue

            if isinstance(default[key], dict):
                self._recursive_set_defaults(current[key], default[key])

    @property
    def image_mode(self):
        return self._image_mode

    @image_mode.setter
    def image_mode(self, v):
        if v == self._image_mode:
            return

        self._image_mode = v
        self.image_mode_changed.emit(v)

    @property
    def active_canvas(self):
        return self._active_canvas

    @active_canvas.setter
    def active_canvas(self, v):
        if v is self._active_canvas:
            return

        self._active_canvas = v
        self.active_canvas_changed.emit()

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
    def has_all_dummy_images(self):
        if not self.imageseries_dict:
            return False

        return all(
            getattr(ims, 'is_dummy', False)
            for ims in self.imageseries_dict.values()
        )

    @property
    def has_images(self):
        # There are images, and they are not dummy images
        return bool(self.imageseries_dict and not self.has_all_dummy_images)

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
        from hexrdgui.create_hedm_instrument import create_hedm_instrument
        instr = create_hedm_instrument()

        if HexrdConfig().apply_pixel_solid_angle_correction:
            sangle = dict.fromkeys(images_dict.keys())
            mi = np.finfo(np.float64).max # largest floating point number
            # normalize by minimum of the entire instrument
            # not each detector individually
            for name, img in images_dict.items():
                panel = instr.detectors[name]
                sangle[name] = panel.pixel_solid_angles
                mi = np.min((mi, sangle[name].min()))
            for name, img in images_dict.items():
                images_dict[name] = mi * img / sangle[name]

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

        if HexrdConfig().apply_absorption_correction:
            transmissions = instr.calc_transmission()
            max_transmission = max(
                [np.nanmax(v) for v in transmissions.values()])

            for name, img in images_dict.items():
                transmission = transmissions[name]
                # normalize by maximum of the entire instrument
                transmission /= max_transmission
                images_dict[name] = img * (1 / transmission)

        if HexrdConfig().intensity_subtract_minimum:
            minimum = min([np.nanmin(x) for x in images_dict.values()])
            for name, img in images_dict.items():
                images_dict[name] = img - minimum

        if HexrdConfig().apply_median_filter_correction:
            for name, img in images_dict.items():
                images_dict[name] = medfilt2d_memoized(
                    img,
                    kernel_size=HexrdConfig().median_filter_kernel_size
                )

        return images_dict

    @property
    def images_dict(self):
        """Default to intensity corrected images dict"""
        return self.intensity_corrected_images_dict

    @property
    def raw_masks_dict(self):
        return self.create_raw_masks_dict(self.images_dict, display=False)

    def create_raw_masks_dict(self, images_dict, display=False):
        """Get a masks dict"""
        from hexrdgui.masking.mask_manager import MaskManager
        masks_dict = {}
        for name, img in images_dict.items():
            final_mask = np.ones(img.shape, dtype=bool)
            for mask in MaskManager().masks.values():
                if display and not mask.visible:
                    # Only apply visible masks for display
                    continue

                if not mask.visible and not mask.show_border:
                    # This mask should not be applied at all.
                    continue

                if mask.type == MaskType.threshold:
                    idx = HexrdConfig().current_imageseries_idx
                    thresh_mask = mask.get_masked_arrays()
                    thresh_mask = thresh_mask[name][idx]
                    final_mask = np.logical_and(final_mask, thresh_mask)
                else:
                    masks = mask.get_masked_arrays(constants.ViewType.raw)
                    for det, arr in masks:
                        if det == name:
                            final_mask = np.logical_and(final_mask, arr)
            masks_dict[name] = final_mask

        return masks_dict

    @property
    def masked_images_dict(self):
        return self.create_masked_images_dict()

    def apply_panel_buffer_to_images(self, images_dict, fill_value=np.nan):
        from hexrdgui.create_hedm_instrument import create_hedm_instrument

        instr = create_hedm_instrument()

        has_panel_buffers = any(panel.panel_buffer is not None
                                for panel in instr.detectors.values())
        if not has_panel_buffers:
            return images_dict

        for det_key, panel in instr.detectors.items():
            # First, ensure the panel buffer is a 2D array
            utils.convert_panel_buffer_to_2d_array(panel)
            img = images_dict[det_key]
            if (np.issubdtype(type(fill_value), np.floating) and
                    not np.issubdtype(img.dtype, np.floating)):
                # Convert to float. This is especially important
                # for nan, since it is a float...
                img = img.astype(float)

            img[~panel.panel_buffer] = fill_value
            images_dict[det_key] = img

        return images_dict

    def create_masked_images_dict(self, fill_value=0, display=False):
        """Get an images dict where masks have been applied"""
        from hexrdgui.masking.mask_manager import MaskManager
        from hexrdgui.create_hedm_instrument import create_hedm_instrument

        images_dict = self.images_dict
        instr = create_hedm_instrument()

        has_masks = bool(MaskManager().visible_masks)
        has_panel_buffers = any(panel.panel_buffer is not None
                                for panel in instr.detectors.values())

        if not has_masks and not has_panel_buffers:
            # Force a fill_value of 0 if there are no visible masks
            # and no panel buffers.
            fill_value = 0

        raw_masks_dict = self.create_raw_masks_dict(images_dict,
                                                    display=display)
        for det, mask in raw_masks_dict.items():
            img = images_dict[det]
            if has_panel_buffers:
                panel = instr.detectors[det]
                utils.convert_panel_buffer_to_2d_array(panel)

            if (np.issubdtype(type(fill_value), np.floating) and
                    not np.issubdtype(img.dtype, np.floating)):
                img = img.astype(float)
                images_dict[det] = img

            img[~mask] = fill_value

            if has_panel_buffers:
                img[~panel.panel_buffer] = fill_value

        return images_dict

    def save_imageseries(self, ims, name, write_file, selected_format,
                         **kwargs):
        hexrd.imageseries.save.write(ims, write_file, selected_format,
                                     **kwargs)

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
            '.yaml': read_yaml,
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

        if not import_raw:
            # Create a backup
            self.backup_instrument_config()

        # Temporarily turn off overlays. They will be updated later.
        self.clear_overlay_data()
        prev = self.show_overlays
        self.config['materials']['show_overlays'] = False
        self.update_visible_material_energies()
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
        from hexrdgui.create_hedm_instrument import create_hedm_instrument

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

        # Make sure the exclusions do not get reset in fit-grains
        cfg['fit_grains']['reset_exclusions'] = False

        current_material = self.indexing_config['_selected_material']
        selected_material = self.material(current_material)
        plane_data = selected_material.planeData

        # tThWidth can be None, bool, or np.float64, in the case of np.float64,
        # we need to convert to float.
        tth_width = plane_data.tThWidth
        if isinstance(tth_width, np.float64):
            tth_width = np.degrees(tth_width).item()

        material = {
            'definitions': 'materials.h5',
            'active': current_material,
            'dmin': selected_material.dmin.getVal('angstrom'),
            'tth_width': tth_width,
            'reset_exclusions': False,
        }

        data = []
        for det in self.detector_names:
            data.append({
                'file': f'{det}.npz',
                'args': {'path': 'imageseries'},
                'panel': det
            })

        image_series = {
            'format': 'frame-cache',
            'data': data
        }

        # Find out which quaternion method was used
        quaternion_method = self.indexing_config['find_orientations'].get(
            '_quaternion_method')

        omaps = cfg['find_orientations']['orientation_maps']

        if quaternion_method == 'seed_search':
            # There must be some active hkls
            active_hkls = omaps['active_hkls']
            if isinstance(active_hkls, np.ndarray):
                active_hkls = active_hkls.tolist()

            if isinstance(active_hkls[0], int):
                # This is a master list. Save the active hkls as the more human
                # readable (h, k, l) tuples instead.
                active_hkls = plane_data.getHKLs(*active_hkls).tolist()

            # Do not save all active hkls, but only the ones used in the seed
            # search. Those are the only ones we need.
            seed_search = cfg['find_orientations']['seed_search']
            active_hkls = [active_hkls[i] for i in seed_search['hkl_seeds']]

            # Renumber the hkl_seeds from 0 to len(hkl_seeds)
            num_hkl_seeds = len(seed_search['hkl_seeds'])
            seed_search['hkl_seeds'] = list(range(num_hkl_seeds))

            omaps['active_hkls'] = active_hkls
        else:
            # Do not need active hkls
            omaps['active_hkls'] = []
            # Seed search settings are not needed
            cfg['find_orientations'].pop('seed_search', None)

        if quaternion_method != 'grid_search':
            # Make sure the file is None
            omaps['file'] = None

        cfg['material'] = material
        cfg['instrument'] = 'instrument.hexrd'
        cfg['image_series'] = image_series
        cfg['working_dir'] = '.'

        with open(output_file, 'w') as f:
            yaml.dump(cfg, f, Dumper=NumpyToNativeDumper)

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
        dist_func_path = ['distortion', 'function_name']
        if len(path) > 3 and path[2:4] == dist_func_path:
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

            self.panel_distortion_modified.emit(path[1])
            return

        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            old_val = cur_val[path[-1]]
            cur_val[path[-1]] = value
        except KeyError:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.config['instrument']))
            raise Exception(msg)

        if old_val == value:
            # If we didn't modify anything, just return
            return

        # If the beam energy was modified, update the visible materials
        beam_path = ['beam']
        if self.has_multi_xrs:
            beam_path.append(self.active_beam_name)

        if path == beam_path + ['energy']:
            self.beam_energy_modified.emit()
            return

        if path[:2] == beam_path + ['vector']:
            # Beam vector has been modified. Indicate so.
            self.beam_vector_changed.emit()
            return

        if path[0] == 'detectors' and path[2] == 'transform':
            # If a detector transform was modified, send a signal
            # indicating so
            det = path[1]
            self.detector_transforms_modified.emit([det])
            return

        if (path[0] == 'detectors' and path[2] == 'pixels'
                and path[3] in ('columns', 'rows')):
            # If the detector shape changes, we need to indicate so.
            # Whatever images that were previously loaded need to be removed,
            # since the shapes will no longer match, and new dummy
            # images loaded with the correct pixel sizes.
            det = path[1]
            self.detector_shape_changed.emit(det)
            self.rerender_needed.emit()
            return

        if path[0] == 'oscillation_stage':
            self.rerender_needed.emit()
            # Overlays need to update their instrument objects when
            # the oscillation stage changes.
            self.oscillation_stage_changed.emit()
            return

        if path[2:4] == ['distortion', 'parameters']:
            self.panel_distortion_modified.emit(path[1])
            return

        # Otherwise, assume we need to re-render the whole image
        self.rerender_needed.emit()

    def get_instrument_config_val(self, path):
        """This obtains a dict value from a path list.

        For instance, if path is [ "beam", "energy" ], it will
        return self.config['instrument']["beam"]["energy"]

        """
        cur_val = self.config['instrument']

        if path[0] == 'beam' and self.has_multi_xrs:
            if path[1] not in self.beam_names:
                # There's going to be one more layer to the path
                path = path.copy()
                path.insert(1, self.active_beam_name)

        # Special case for distortion:
        # If no distortion is specified, return 'None'
        dist_func_path = ['distortion', 'function_name']
        if len(path) > 3 and path[2:4] == dist_func_path:
            for val in path:
                if val not in cur_val:
                    return 'None'
                cur_val = cur_val[val]
            return cur_val

        try:
            for val in path:
                cur_val = cur_val[val]
        except KeyError:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.config['instrument']))
            raise KeyError(msg)

        return cur_val

    def set_val_from_widget_name(self, widget_name, value, detector=None):
        yaml_paths = self.get_gui_yaml_paths()
        for var, path in yaml_paths:
            if var == widget_name:
                if 'detector_name' in path:
                    # Replace detector_name with the detector name
                    path[path.index('detector_name')] = detector

                    if self.rotation_matrix_euler() is not None:
                        tilt_path = ['transform', 'tilt']
                        if path[2:-1] == tilt_path:
                            # This will be in degrees. Convert to radians.
                            value = np.radians(value).item()
                else:
                    chi_path = ['oscillation_stage', 'chi']
                    if path == chi_path:
                        # This will be in degrees. Convert to radians.
                        value = np.radians(value).item()

                if path[0] == 'beam' and self.has_multi_xrs:
                    path = path.copy()
                    path.insert(1, self.active_beam_name)

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

    @property
    def instrument_has_roi(self):
        det = next(iter(self.detectors.values()))

        # Both the group and roi must be present to support ROI
        has_group = det.get('group', {})
        has_roi = det.get('pixels', {}).get('roi', {})
        return bool(has_group and has_roi)

    @property
    def detector_group_names(self):
        names = []
        for det_key in self.detectors:
            name = self.detector_group(det_key)
            if name and name not in names:
                names.append(name)

        return names

    def detector_group(self, detector_name):
        det = self.detector(detector_name)
        return det.get('group', {})

    def detector_pixel_size(self, detector_name):
        detector = self.detector(detector_name)
        return detector.get('pixels', {}).get('size', [0.1, 0.1])

    def add_detector(self, detector_name, detector_to_copy=None, config=None):
        if config is not None:
            new_detector = copy.deepcopy(config)
        elif detector_to_copy is not None:
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
        module = hexrdgui.resources.materials
        with resource_loader.path(module, 'materials.h5') as file_path:
            with h5py.File(file_path) as f:
                return list(f.keys())

    # This section is for materials configuration
    def load_default_material(self, name):
        module = hexrdgui.resources.materials
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
        for polar_overlay in self.azimuthal_overlays:
            if polar_overlay['material'] == old_name:
                polar_overlay['material'] = new_name

        if self.active_material_name == old_name:
            # Set the dict directly to bypass the updates that occur
            # if we did self.active_material = new_name
            self.config['materials']['active_material'] = new_name

        self.material_renamed.emit(old_name, new_name)

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

        with utils.block_signals(self):
            # Prevent the GUI from updating while we are in an invalid
            # state.
            self.prune_overlays()

        if materials.keys():
            self.active_material = list(materials.keys())[0]

        self.flag_overlay_updates_for_all_materials()
        self.overlay_config_changed.emit()

        self.materials_set.emit()

    materials = property(_materials, _set_materials)

    def material(self, name):
        return self.config['materials']['materials'].get(name)

    def check_active_material_changed(self, material_name):
        if material_name == self.active_material_name:
            self.active_material_modified.emit()

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
    def has_multi_xrs(self):
        beam = self.config['instrument']['beam']
        return beam and 'energy' not in beam

    @property
    def beam_energy(self):
        return self.xrs_beam_energy(self.active_beam_name)

    def beam_dict(self, beam_name: str | None) -> dict:
        cfg = self.config['instrument']['beam']
        return cfg if beam_name is None else cfg[beam_name]

    def xrs_beam_energy(self, beam_name: str | None) -> float:
        if beam_name is None and self.has_multi_xrs:
            # Use the active x-ray source
            beam_name = self.active_beam_name

        return self.beam_dict(beam_name)['energy']

    @property
    def active_beam(self):
        return self.beam_dict(self.active_beam_name)

    @property
    def beam_wavelength(self):
        energy = self.beam_energy
        return constants.KEV_TO_WAVELENGTH / energy if energy else None

    @property
    def beam_names(self) -> list[str]:
        if not self.has_multi_xrs:
            return ['XRS1']

        return list(self.config['instrument']['beam'])

    @property
    def active_beam_name(self) -> str | None:
        if not self.has_multi_xrs:
            return None

        if self._active_beam_name is None:
            # Set it to the first XRS
            self._active_beam_name = next(iter(self.beam_dict(None)))

        return self._active_beam_name

    @active_beam_name.setter
    def active_beam_name(self, v: str | None):
        if not self.has_multi_xrs:
            self._active_beam_name = None
            return

        if self._active_beam_name == v:
            # Don't need to do anything...
            return

        self._active_beam_name = v
        self._shift_eta_if_tardis()
        self.active_beam_switched.emit()

        if self.image_mode == constants.ViewType.polar:
            self.deep_rerender_needed.emit()

    def _shift_eta_if_tardis(self):
        # TARDIS users will always shift eta by 180 degrees when
        # the active beam has been switched. We will do that
        # automatically for convenience.

        tardis_names = constants.KNOWN_DETECTOR_NAMES['TARDIS']
        if not all(name in tardis_names for name in self.detector_names):
            # Assume this is not TARDIS...
            return

        eta_configurations = {
            'XRS1': (0, 360),
            'XRS2': (-180, 180),
        }
        if self.active_beam_name not in eta_configurations:
            # This is unexpected and shouldn't happen
            return

        eta_range = eta_configurations[self.active_beam_name]

        # We should be triggering a rerender already outside of this function,
        # so don't trigger another one here.
        self.set_polar_res_eta_min(eta_range[0], rerender=False)
        self.set_polar_res_eta_max(eta_range[1], rerender=False)

    def update_material_energy(self, mat):
        energy = self.beam_energy

        # This is a potentially expensive operation...
        # If the plane data energy already matches, skip it
        pd_wavelength = mat.planeData.wavelength
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

        # Also update the energy of the active material, since
        # its reflections table is visible.
        self.update_material_energy(self.active_material)

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
        pruned_overlays = [x for x in self.overlays if x.material_name in mats]
        if len(self.overlays) != len(pruned_overlays):
            self.overlays = pruned_overlays
            self.overlay_list_modified.emit()
            self.overlay_config_changed.emit()

        pruned_overlays = [x for x in self.azimuthal_overlays
                           if x['material'] in mats]
        if len(self.azimuthal_overlays) != len(pruned_overlays):
            self.azimuthal_overlays = pruned_overlays
            HexrdConfig().azimuthal_options_modified.emit()

    def append_overlay(self, material_name, type):
        kwargs = {
            'material_name': material_name,
            'type': type,
        }
        overlay = overlays.create_overlay(**kwargs)
        self.overlays.append(overlay)
        self.overlay_list_modified.emit()
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
        self.overlay_list_modified.emit()

    def clear_overlay_data(self):
        for overlay in self.overlays:
            overlay.update_needed = True

    def reset_overlay_calibration_picks(self):
        for overlay in self.overlays:
            overlay.reset_calibration_picks()

    def flag_overlay_updates_for_active_material(self):
        self.flag_overlay_updates_for_material(self.active_material_name)

    def flag_overlay_updates_for_material(self, material_name):
        for overlay in self.overlays:
            if overlay.material_name == material_name:
                overlay.update_needed = True

    def flag_overlay_updates_for_all_materials(self):
        for name in self.materials:
            self.flag_overlay_updates_for_material(name)

    @property
    def sample_tilt(self):
        return self._sample_tilt

    @sample_tilt.setter
    def sample_tilt(self, v):
        v = np.asarray(v, float)
        if np.array_equal(v, self.sample_tilt):
            return

        self._sample_tilt = v
        self.sample_tilt_modified.emit()

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

    @property
    def polar_tth_distortion(self):
        return self.polar_tth_distortion_object is not None

    @property
    def polar_tth_distortion_object(self):
        # If a custom object has been set, use it (this overrides an overlay)
        if self.custom_polar_tth_distortion_object:
            return self.custom_polar_tth_distortion_object

        # Otherwise, try using the distortion overlay.
        return self.polar_tth_distortion_overlay

    @polar_tth_distortion_object.setter
    def polar_tth_distortion_object(self, v):
        if isinstance(v, (str, overlays.Overlay)):
            # It's an overlay or the name of an overlay
            self.custom_polar_tth_distortion_object = None
            self.polar_tth_distortion_overlay = v
            return
        elif v is None:
            # Set both to None
            self.polar_tth_distortion_overlay = None
            self.custom_polar_tth_distortion_object = None
            return

        # Must be a custom distortion object
        self.custom_polar_tth_distortion_object = v

    @property
    def custom_polar_tth_distortion_object(self):
        return self._custom_polar_tth_distortion_object

    @custom_polar_tth_distortion_object.setter
    def custom_polar_tth_distortion_object(self, v):
        if v is self._custom_polar_tth_distortion_object:
            return

        name = v.name if v else None

        self._custom_polar_tth_distortion_object = v
        if v is not None:
            self.saved_custom_polar_tth_distortion_object = v

        self.overlay_distortions_modified.emit(name)
        self.flag_overlay_updates_for_all_materials()
        self.rerender_needed.emit()
        self.polar_tth_distortion_overlay_changed.emit()

    @property
    def custom_polar_tth_distortion_object_serialized(self):
        obj = self.saved_custom_polar_tth_distortion_object
        if obj is None:
            return None

        return {
            'active': self.polar_tth_distortion_object is obj,
            'serialized': obj.serialize(),
        }

    @custom_polar_tth_distortion_object_serialized.setter
    def custom_polar_tth_distortion_object_serialized(self, v):
        obj = None
        if v is not None:
            if not self.has_physics_package:
                # This requires a physics package to deserialize
                self.create_default_physics_package()

            active = v['active']
            d = v['serialized']
            if d.get('pinhole_distortion_type') == 'SampleLayerDistortion':
                # We added pinhole_radius later. Set a default if it is missing.
                if 'pinhole_radius' not in d['pinhole_distortion_kwargs']:
                    radius = self.physics_package.pinhole_radius
                    d['pinhole_distortion_kwargs']['pinhole_radius'] = radius * 1e-3

            from hexrdgui.polar_distortion_object import PolarDistortionObject
            obj = PolarDistortionObject.deserialize(d)

        if obj and active:
            self.polar_tth_distortion_object = obj
        else:
            self.saved_custom_polar_tth_distortion_object = obj

    @property
    def polar_tth_distortion_overlay(self):
        name = self._polar_tth_distortion_overlay_name
        if name is None:
            return None

        for overlay in self.overlays:
            if overlay.name == name:
                return overlay

        # This overlay must not exist
        return None

    @polar_tth_distortion_overlay.setter
    def polar_tth_distortion_overlay(self, overlay):
        if isinstance(overlay, overlays.Overlay):
            name = overlay.name
        else:
            # Assume it is the name or None
            name = overlay

        if self._polar_tth_distortion_overlay_name != name:
            self._polar_tth_distortion_overlay_name = name
            self.flag_overlay_updates_for_all_materials()
            self.rerender_needed.emit()
            self.polar_tth_distortion_overlay_changed.emit()

    @property
    def polar_apply_scaling_to_lineout(self):
        return self.config['image']['polar']['apply_scaling_to_lineout']

    @polar_apply_scaling_to_lineout.setter
    def polar_apply_scaling_to_lineout(self, b):
        if b == self.polar_apply_scaling_to_lineout:
            return

        self.config['image']['polar']['apply_scaling_to_lineout'] = b
        self.rerender_needed.emit()

    def set_polar_apply_scaling_to_lineout(self, b):
        self.polar_apply_scaling_to_lineout = b

    @property
    def polar_x_axis_type(self):
        return self.config['image']['polar']['x_axis_type']

    @polar_x_axis_type.setter
    def polar_x_axis_type(self, v):
        if v == self.polar_x_axis_type:
            return

        self.config['image']['polar']['x_axis_type'] = v
        self.polar_x_axis_type_changed.emit()

    def on_overlay_renamed(self, old_name, new_name):
        if self._polar_tth_distortion_overlay_name == old_name:
            self._polar_tth_distortion_overlay_name = new_name

    def _cartesian_pixel_size(self):
        return self.config['image']['cartesian']['pixel_size']

    def _set_cartesian_pixel_size(self, v):
        if v != self.cartesian_pixel_size:
            self.config['image']['cartesian']['pixel_size'] = v
            if self.image_mode == constants.ViewType.cartesian:
                self.rerender_needed.emit()

    cartesian_pixel_size = property(_cartesian_pixel_size,
                                    _set_cartesian_pixel_size)

    def _cartesian_virtual_plane_distance(self):
        return self.config['image']['cartesian']['virtual_plane_distance']

    def set_cartesian_virtual_plane_distance(self, v):
        if v < 0:
            raise RuntimeError(f'Invalid plane distance: {v}')

        if v != self.cartesian_virtual_plane_distance:
            self.config['image']['cartesian']['virtual_plane_distance'] = v
            if self.image_mode == constants.ViewType.cartesian:
                self.rerender_needed.emit()

    cartesian_virtual_plane_distance = property(
        _cartesian_virtual_plane_distance,
        set_cartesian_virtual_plane_distance)

    def _cartesian_plane_normal_rotate_x(self):
        return self.config['image']['cartesian']['plane_normal_rotate_x']

    def set_cartesian_plane_normal_rotate_x(self, v):
        if v != self.cartesian_plane_normal_rotate_x:
            self.config['image']['cartesian']['plane_normal_rotate_x'] = v
            if self.image_mode == constants.ViewType.cartesian:
                self.rerender_needed.emit()

    cartesian_plane_normal_rotate_x = property(
        _cartesian_plane_normal_rotate_x,
        set_cartesian_plane_normal_rotate_x)

    def _cartesian_plane_normal_rotate_y(self):
        return self.config['image']['cartesian']['plane_normal_rotate_y']

    def set_cartesian_plane_normal_rotate_y(self, v):
        if v != self.cartesian_plane_normal_rotate_y:
            self.config['image']['cartesian']['plane_normal_rotate_y'] = v
            if self.image_mode == constants.ViewType.cartesian:
                self.rerender_needed.emit()

    cartesian_plane_normal_rotate_y = property(
        _cartesian_plane_normal_rotate_y,
        set_cartesian_plane_normal_rotate_y)

    def _stereo_size(self):
        return self.config['image']['stereo']['stereo_size']

    def set_stereo_size(self, v):
        if v != self.stereo_size:
            self.config['image']['stereo']['stereo_size'] = v
            self.rerender_needed.emit()

    stereo_size = property(_stereo_size, set_stereo_size)

    def _stereo_show_border(self):
        return self.config['image']['stereo']['show_border']

    def set_stereo_show_border(self, b):
        if b != self.stereo_size:
            self.config['image']['stereo']['show_border'] = b
            self.show_stereo_border_changed.emit()

    stereo_show_border = property(_stereo_show_border, set_stereo_show_border)

    def _stereo_project_from_polar(self):
        return self.config['image']['stereo']['project_from_polar']

    def set_stereo_project_from_polar(self, b):
        if not b:
            print('Warning: projecting from raw is currently disabled\n',
                  'Setting stereo mode to project from polar...')
            b = True

        if b != self.stereo_project_from_polar:
            self.config['image']['stereo']['project_from_polar'] = b
            self.rerender_needed.emit()

    stereo_project_from_polar = property(
        _stereo_project_from_polar,
        set_stereo_project_from_polar)

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
            'apply_absorption_correction',
            'apply_median_filter_correction',
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

    def get_stitch_raw_roi_images(self):
        return self._stitch_raw_roi_images and self.instrument_has_roi

    def set_stitch_raw_roi_images(self, v):
        if self._stitch_raw_roi_images != v:
            self._stitch_raw_roi_images = v
            self.deep_rerender_needed.emit()

    stitch_raw_roi_images = property(get_stitch_raw_roi_images,
                                     set_stitch_raw_roi_images)

    def tab_images(self):
        return self._tab_images

    def set_tab_images(self, v):
        if self._tab_images != v:
            self._tab_images = v
            self.tab_images_changed.emit()

    tab_images = property(tab_images, set_tab_images)

    @property
    def font_size(self):
        return QCoreApplication.instance().font().pointSize()

    @font_size.setter
    def font_size(self, v):
        # Make sure this is an int
        v = int(v)

        app = QCoreApplication.instance()
        font = app.font()
        font.setPointSize(v)
        app.setFont(font)

        # Update the matplotlib font size too
        if matplotlib.rcParams['font.size'] != v:
            matplotlib.rcParams.update({'font.size': v})
            self.deep_rerender_needed.emit()

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
        iconfig = copy.deepcopy(self.instrument_config)
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
        elif func_name == 'Dexela_2923_quad':
            return 6

        raise Exception('Unknown distortion function: ' + func_name)

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

    @property
    def recent_images(self):
        return self._recent_images

    @recent_images.setter
    def recent_images(self, images):
        v = {}
        for det, imgs in zip(self.detector_names, images):
            v[det] = imgs if isinstance(imgs, list) else [imgs]
        self._recent_images = v
        self.recent_images_changed.emit()

    def clean_panel_buffers(self):
        # Ensure that the panel buffer sizes match the pixel sizes.
        # If not, clear the panel buffer and print a warning.
        for name, det_info in self.detectors.items():
            buffer = det_info.get('buffer')
            if buffer is None:
                continue

            buffer = np.asarray(buffer)
            if buffer.ndim == 1:
                continue

            columns = det_info['pixels']['columns']
            rows = det_info['pixels']['rows']
            det_shape = (rows, columns)
            if buffer.shape != det_shape:
                # The user may have had some old config settings here
                # with a different sized panel buffer than what we have now.
                # Instead of allowing an error to occur, print out a warning
                # and delete the panel buffer.
                self.logger.warning(
                    f'Warning: detector "{name}": panel buffer shape {buffer.shape} '
                    f'does not match detector shape {det_shape}. '
                    'Clearing panel buffer.'
                )
                det_info['buffer'] =  [0., 0.]

    def add_recent_state_file(self, new_file):
        self.recent_state_files.insert(0, str(new_file))
        # Maintain order and ensure no duplicate entries
        recent = list(dict.fromkeys(self.recent_state_files))
        while len(recent) > 10:
            recent.pop(-1)
        self.recent_state_files = recent

    @property
    def apply_absorption_correction(self):
        return self._apply_absorption_correction

    @apply_absorption_correction.setter
    def apply_absorption_correction(self, v):
        if v != self.apply_absorption_correction:
            self._apply_absorption_correction = v
            self.deep_rerender_needed.emit()

    @property
    def physics_package_dictified(self):
        if not self.has_physics_package:
            return {}

        return self.physics_package.serialize()

    @physics_package_dictified.setter
    def physics_package_dictified(self, kwargs):
        if not kwargs:
            self.physics_package = None
            return

        # Set defaults if missing
        kwargs = {
            **PHYSICS_PACKAGE_DEFAULTS.HED,
            **kwargs,
        }
        self.physics_package = HEDPhysicsPackage(**kwargs)

    def update_physics_package(self, **kwargs):
        self.physics_package_dictified = {
            **self.physics_package_dictified,
            **kwargs,
        }

    @property
    def physics_package(self):
        return self._physics_package

    @physics_package.setter
    def physics_package(self, value):
        if value != self._physics_package:
            self._physics_package = value
            self.physics_package_modified.emit()

    @property
    def has_physics_package(self) -> bool:
        return self.physics_package is not None

    def create_default_physics_package(self):
        # Our default will be an HED Physics package with a pinhole
        self.physics_package_dictified = {
            **PHYSICS_PACKAGE_DEFAULTS.HED,
            **PINHOLE_DEFAULTS.TARDIS,
        }

    def absorption_length(self):
        if not self.has_physics_package:
            raise ValueError(
                f'Cannot calculate absorption length without physics package')
        return self.physics_package.pinhole_absorption_length(
            HexrdConfig().beam_energy)

    @property
    def detector_coatings_dictified(self):
        d = {}
        for k, v in self._detector_coatings.items():
            d[k] = {}
            for attr, cls in v.items():
                if cls is not None:
                    d[k][attr] = cls.serialize()

            if not d[k]:
                del d[k]

        return d

    @detector_coatings_dictified.setter
    def detector_coatings_dictified(self, v):
        funcs = {
            'coating': self.update_detector_coating,
            'filter': self.update_detector_filter,
            'phosphor': self.update_detector_phosphor,
        }
        for det, val in v.items():
            all_coatings = self._detector_coatings.setdefault(det, {})
            for k, f in funcs.items():
                if val.get(k) is not None:
                    f(det, **val[k])
                else:
                    all_coatings[k] = None

    def _set_detector_coatings(self, key):
        for name in self.detector_names:
            self._detector_coatings.setdefault(name, {})

        dets = list(self._detector_coatings.values())
        if all([key in det for det in dets]):
            return

        from hexrdgui.create_hedm_instrument import create_hedm_instrument
        instr = create_hedm_instrument()
        for name, det in instr.detectors.items():
            if key not in self._detector_coatings[name]:
                self._detector_coatings[name][key] = getattr(det, key)

    def detector_filter(self, det_name):
        self._detector_coatings.setdefault(det_name, {})
        return self._detector_coatings[det_name].get('filter', None)

    def update_detector_filter(self, det_name, **kwargs):
        if det_name not in self.detector_names:
            return None
        self._set_detector_coatings('filter')
        filter = self._detector_coatings[det_name]['filter']
        filter.deserialize(**kwargs)

    def detector_coating(self, det_name):
        self._detector_coatings.setdefault(det_name, {})
        return self._detector_coatings[det_name].get('coating', None)

    def update_detector_coating(self, det_name, **kwargs):
        if det_name not in self.detector_names:
            return None
        self._set_detector_coatings('coating')
        coating = self._detector_coatings[det_name]['coating']
        coating.deserialize(**kwargs)

    def detector_phosphor(self, det_name):
        self._detector_coatings.setdefault(det_name, {})
        return self._detector_coatings[det_name].get('phosphor', None)

    def update_detector_phosphor(self, det_name, **kwargs):
        if det_name not in self.detector_names:
            return None
        self._set_detector_coatings('phosphor')
        phosphor = self._detector_coatings[det_name]['phosphor']
        phosphor.deserialize(**kwargs)

    @property
    def apply_median_filter_correction(self):
        return self._median_filter_correction.get('apply', False)

    @apply_median_filter_correction.setter
    def apply_median_filter_correction(self, v):
        if v != self.apply_median_filter_correction:
            self._median_filter_correction['apply'] = v
            self.deep_rerender_needed.emit()

    @property
    def median_filter_kernel_size(self):
        return self._median_filter_correction.get('kernel', 7)

    @median_filter_kernel_size.setter
    def median_filter_kernel_size(self, v):
        if v != self.median_filter_kernel_size:
            self._median_filter_correction['kernel'] = int(v)
            self.deep_rerender_needed.emit()


# This is set to (num_fiddle_plates * num_time_steps) + num_image_plates
# This feature is primarily for FIDDLE
@memoize(maxsize=21)
def medfilt2d_memoized(img: np.ndarray, kernel_size: int):
    return medfilt2d(img, kernel_size)
