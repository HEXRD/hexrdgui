import glob
import os
import re
import sys
import numpy as np
import yaml
import tempfile
import h5py
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QColorDialog, QFileDialog, QMessageBox
from PySide6.QtGui import QColor

from hexrd import resources as hexrd_resources
from hexrd.instrument import HEDMInstrument
from hexrd.rotations import (
    angleAxisOfRotMat,
    make_rmat_euler,
    angles_from_rmat_zxz,
    rotMatOfExpMap,
)

import hexrdgui.resources.calibration
from hexrdgui.constants import (
    FIDDLE_FRAMES,
    FIDDLE_HDF5_PATH,
    UI_TRANS_INDEX_NONE,
    UI_TRANS_INDEX_ROTATE_90,
    YAML_EXTS,
    LLNLTransform,
    ViewType,
    FIDDLE_SMR_CMM,
    FIDDLE_ICARUS_CORNERS_CMM,
    KNOWN_DETECTOR_NAMES,
)
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_file_manager import ImageFileManager
from hexrdgui.image_load_manager import ImageLoadManager
from hexrdgui.interactive_template import InteractiveTemplate
from hexrdgui import resource_loader
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import instr_to_internal_dict, block_signals
from hexrdgui.utils.dialog import add_help_url

from lmfit import Parameters, Minimizer


class AtlasConfig:
    def __init__(self, raw_data, instr):

        self.instr = instr
        self.raw_data = raw_data
        self.compute_result_and_coords()

    def _determine_coordinate_transform(self, start, finish):

        def optimization_function(params, start, finish):
            alpha = params['alpha'].value
            beta = params['beta'].value
            gamma = params['gamma'].value

            tilt = np.radians([alpha, beta, gamma])

            rmat = make_rmat_euler(tilt, 'xyz', extrinsic=True)

            trans = np.atleast_2d(
                np.array(
                    [
                        params['tvec_x'].value,
                        params['tvec_y'].value,
                        params['tvec_z'].value,
                    ]
                )
            )

            trans_start = np.dot(rmat, start.T).T + np.repeat(
                trans, start.shape[0], axis=0
            )

            residual = trans_start - finish
            return residual.flatten()

        params = Parameters()
        params.add(name='alpha', value=0, vary=True)
        params.add(name='beta', value=0, vary=True)
        params.add(name='gamma', value=0, vary=True)

        params.add(name='tvec_x', value=0, vary=True)
        params.add(name='tvec_y', value=0, vary=True)
        params.add(name='tvec_z', value=0, vary=True)

        args = (start, finish)

        res = Minimizer(optimization_function, params, fcn_args=args)

        minimizer_result = res.minimize(method='least_squares', params=params)

        if minimizer_result.chisqr > 1:
            msg = (
                f'least-squares did not find a good solution. '
                f'Double check data to make sure input is in order.'
            )
            print(msg, file=sys.stderr)
            QMessageBox.warning(None, 'HEXRD', msg)

        return minimizer_result

    def _transform_coordinates(self, pts):
        return np.dot(self.rmat, pts.T).T + np.repeat(self.tvec, pts.shape[0], axis=0)

    def _get_icarus_corners_in_TCC(self):
        IC_TCC = self._transform_coordinates(FIDDLE_ICARUS_CORNERS_CMM)
        # Check shape of IC_TCC. Should be 20 x 3
        if IC_TCC.shape != (20, 3):
            msg = (
                f'shape of the icarus corner coordinates is incorrect. Shape '
                f'should be (20, 3). Input shape is {IC_TCC.shape}'
            )
            raise RuntimeError(msg)
        coords = dict.fromkeys(KNOWN_DETECTOR_NAMES['FIDDLE'])
        for ii, k in enumerate(coords.keys()):
            coords[k] = IC_TCC[ii * 4 : (ii + 1) * 4, :]
        return coords

    def _get_orientation(self, crds, det):
        # Vertex in 4x3 matrix of the 4 vertices.
        # We return the normal using a cross product
        vertex = self._get_vertices(crds)
        if det == 'CAMERA-05':
            xhat = -vertex[1, :] + vertex[0, :]
            yhat = vertex[3, :] - vertex[0, :]
        else:
            xhat = vertex[3, :] - vertex[0, :]
            yhat = vertex[1, :] - vertex[0, :]

        xhat = xhat / np.linalg.norm(xhat)
        yhat = yhat / np.linalg.norm(yhat)

        zhat = np.cross(xhat, yhat)
        zhat = zhat / np.linalg.norm(zhat)

        xhat = np.cross(yhat, zhat)
        xhat = xhat / np.linalg.norm(xhat)

        rmat = np.vstack((-xhat, yhat, -zhat)).T

        RMAT_Z_180 = rotMatOfExpMap(np.pi * zhat)
        if det in ['CAMERA-02', 'CAMERA-03']:
            return np.dot(RMAT_Z_180, rmat)
        return rmat

    def _get_center(self, vertex):
        # Return center of detector given the four vertices
        return np.mean(vertex, axis=0)

    def _get_vertices(self, crds):
        # By default we will look up from TCC, so
        # there is a flip in the x-component sign
        return crds[0:4, :]

    def update_instrument(self, detector):
        v = self._get_vertices(self.coords[detector])

        # tvec sample is the position of the sample in NIF
        # chamber coordinates. the position of each detector
        # is measured from this point, so we need to take this
        # off
        tvec_sample = np.array([0, 0, 9.85])
        tvec = self._get_center(v) - tvec_sample
        rmat = self._get_orientation(self.coords[detector], detector)
        ang, ax = angleAxisOfRotMat(rmat)
        self.instr.detectors[detector].tvec = tvec
        self.instr.detectors[detector].tilt = ang * ax

    def compute_result_and_coords(self):
        # get the coordinate transform connecting SMR in CMM to the TCC frame
        self.minimizer_result = self._determine_coordinate_transform(
            FIDDLE_SMR_CMM, self.atlas_coords_array
        )
        self.coords = self._get_icarus_corners_in_TCC()

    @property
    def rmat(self):
        if hasattr(self, 'minimizer_result'):
            params = self.minimizer_result.params
            alpha = params['alpha'].value
            beta = params['beta'].value
            gamma = params['gamma'].value
            tilt = np.radians([alpha, beta, gamma])
            return make_rmat_euler(tilt, 'xyz', extrinsic=True)
        else:
            return np.eye(3)

    @property
    def tvec(self):
        if hasattr(self, 'minimizer_result'):
            params = self.minimizer_result.params
            return np.atleast_2d(
                np.array(
                    [
                        params['tvec_x'].value,
                        params['tvec_y'].value,
                        params['tvec_z'].value,
                    ]
                )
            )
        else:
            return np.zeros(
                [
                    3,
                ]
            )

    @property
    def atlas_coords_array(self):
        # Return atlas coordinates as array
        atlas_coords_array = []
        for k, v in self.raw_data.items():
            atlas_coords_array.append(v)
        return np.array(atlas_coords_array)


class LLNLImportToolDialog(QObject):

    # Emitted when new config is loaded
    new_config_loaded = Signal()

    # Emitted when an instrument was selected
    instrument_was_selected = Signal()

    # Emitted when the workflow is canceled
    cancel_workflow = Signal()

    # The boolean flag indicates whether this is a FIDDLE instrument or not
    complete_workflow = Signal(bool)

    def __init__(self, cmap=None, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('llnl_import_tool_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        add_help_url(self.ui.button_box, 'configuration/images/#llnl-import-tool')

        self.it = None
        self.instrument = None
        self.edited_images = {}
        self.completed = []
        self.canvas = parent.image_tab_widget.image_canvases[0]
        self.ip_and_det_defaults = {}
        self.cmap = cmap
        self.image_plates = []
        self.detectors = []
        self.current_image_selection = None
        self.defaults = {}
        self.import_in_progress = False
        self.loaded_images = {}
        self.canvas = parent.image_tab_widget.active_canvas
        self.detector_images = {}
        self.atlas_coords = None
        self._image_plate = None

        # Disable these by default.
        # If we disable these in Qt Designer, there are some weird bugs
        # that happen in Designer, so just disable them here.
        self.enable_widgets(
            self.ui.image_plate_raw_image,
            self.ui.config,
            self.ui.file_selection,
            self.ui.finalize,
            self.ui.outline_appearance,
            self.ui.template_instructions,
            self.ui.detector_raw_image,
            enabled=False,
        )

        # We have different needs for different instruments. Hide optional
        # widgets until the instrument is selected.
        self.set_widget_visibility(
            self.ui.image_plate_raw_image,
            self.ui.template_instructions,
            self.ui.outline_appearance,
            self.ui.detector_raw_image,
            self.ui.instr_settings_label,
            self.ui.instr_settings,
            self.ui.load_atlas,
            self.ui.atlas_label,
            self.ui.completed_dets_and_ips,
            visible=False,
        )

        self.update_config_settings()

        self.set_default_color()
        self.setup_connections()

    def setup_connections(self):
        self.ui.instruments.currentIndexChanged.connect(self.instrument_selected)
        self.ui.image_plate_load.clicked.connect(self.load_images)
        self.ui.image_plates.currentIndexChanged.connect(self.image_plate_selected)
        self.ui.detectors.currentIndexChanged.connect(self.detector_selected)
        self.ui.add_transform.clicked.connect(self.add_transform)
        self.ui.accept_template.clicked.connect(self.complete_current_selection)
        self.ui.complete.clicked.connect(self.import_complete)
        self.ui.bb_height.valueChanged.connect(self.update_bbox_height)
        self.ui.bb_width.valueChanged.connect(self.update_bbox_width)
        self.ui.line_style.currentIndexChanged.connect(self.update_template_style)
        self.ui.line_color.clicked.connect(self.pick_line_color)
        self.ui.line_size.valueChanged.connect(self.update_template_style)
        self.ui.cancel.clicked.connect(self.on_canceled)
        self.ui.load_config.clicked.connect(self.load_config)
        self.ui.config_selection.currentIndexChanged.connect(
            self.update_config_selection
        )
        self.ui.config_settings.currentIndexChanged.connect(
            # This will update the instrument defaults to the config settings
            self.get_instrument_defaults
        )
        self.ui.instr_settings.currentIndexChanged.connect(
            self.instrument_settings_changed
        )
        self.ui.detector_load.clicked.connect(self.load_detector_images)
        self.ui.dark_load.clicked.connect(self.load_detector_images)
        self.ui.accept_detector.clicked.connect(self.manually_load_detector_images)
        self.ui.load_atlas.clicked.connect(self.load_atlas_coords)

    def enable_widgets(self, *widgets, enabled):
        for w in widgets:
            w.setEnabled(enabled)

    def set_widget_visibility(self, *widgets, visible):
        for w in widgets:
            w.setVisible(visible)
            w.setEnabled(visible)

    def set_default_color(self):
        self.outline_color = '#00ffff'
        self.ui.line_color.setText(self.outline_color)
        self.ui.line_color.setStyleSheet('QPushButton {background-color: cyan}')

    def get_instrument_defaults(self):
        self.ip_and_det_defaults.clear()
        not_default = self.ui.config_selection.currentIndex() != 0
        if self.config_file and not_default:
            if os.path.splitext(self.config_file)[1] in YAML_EXTS:
                with open(self.config_file, 'r') as f:
                    instr_config = yaml.safe_load(f)

                instr = HEDMInstrument(instr_config)
                self.defaults = instr_to_internal_dict(instr, convert_tilts=False)
            else:
                try:
                    with h5py.File(self.config_file, 'r') as f:
                        instr = HEDMInstrument(f)
                        self.defaults = instr_to_internal_dict(
                            instr, convert_tilts=False
                        )
                except Exception as e:
                    msg = (
                        f'ERROR - Could not read file: \n {e} \n'
                        f'File must be HDF5 or YAML.'
                    )
                    QMessageBox.warning(None, 'HEXRD', msg)
                    return False
        else:
            if self.has_config_settings:
                # This must be TARDIS with default configuration
                filenames = {
                    '1 XRS': 'tardis_reference_config.yml',
                    '2 XRS': 'tardis_2xrs_reference_config.yml',
                }
                fname = filenames[self.config_setting]
            else:
                fname = f'{self.instrument.lower()}_reference_config.yml'

            text = resource_loader.load_resource(hexrd_resources, fname)
            self.defaults = yaml.safe_load(text)
        self.ip_and_det_defaults['default_config'] = self.defaults
        self.set_detector_options()

    def set_detector_options(self):
        self.image_plates.clear()
        self.detectors.clear()
        for det, vals in self.defaults['detectors'].items():
            self.ip_and_det_defaults[det] = vals['transform']
            if 'IMAGE-PLATE' in det or self.instrument != 'FIDDLE':
                self.image_plates.append(det)
            else:
                self.detectors.append(det)

        self.ui.image_plates.clear()
        self.ui.image_plates.addItems(self.image_plates)
        self.ui.detectors.clear()
        self.ui.detectors.addItems(self.detectors)

    def load_config(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui,
            'Load Configuration',
            HexrdConfig().working_dir,
            'HEXRD files (*.hexrd *.yml)',
        )
        self.config_file = selected_file if selected_file else None
        self.ui.config_file_label.setText(os.path.basename(self.config_file))
        self.ui.config_file_label.setToolTip(self.config_file)
        if self.ui.instrument.isEnabled():
            self.get_instrument_defaults()

    def instrument_settings_changed(self, index):
        has_ip = index == 0
        self.set_widget_visibility(
            self.ui.image_plate_raw_image,
            self.ui.template_instructions,
            self.ui.outline_appearance,
            visible=has_ip,
        )

    def instrument_selected(self, idx):
        instruments = {1: 'TARDIS', 2: 'PXRDIP', 3: 'FIDDLE'}
        self.instrument = instruments.get(idx, None)

        if HexrdConfig().show_beam_marker:
            HexrdConfig().show_beam_marker = False

        self.reset_panel()
        HexrdConfig().restore_instrument_config_backup()
        self.image_plates.clear()
        self.detectors.clear()
        self.ip_and_det_defaults.clear()

        if self.instrument is None:
            HexrdConfig().enable_canvas_toolbar.emit(True)
            self.update_config_settings()
            self.set_widget_visibility(
                self.ui.image_plate_raw_image,
                self.ui.template_instructions,
                self.ui.outline_appearance,
                self.ui.detector_raw_image,
                visible=False,
            )
        else:
            is_fiddle = self.instrument == 'FIDDLE'
            self.set_widget_visibility(
                self.ui.detector_raw_image,
                self.ui.instr_settings_label,
                self.ui.instr_settings,
                self.ui.load_atlas,
                self.ui.atlas_label,
                visible=is_fiddle,
            )

            has_ip = self.ui.instr_settings.currentIndex() == 0
            needs_mask = not is_fiddle or has_ip
            self.set_widget_visibility(
                self.ui.image_plate_raw_image,
                self.ui.template_instructions,
                self.ui.outline_appearance,
                visible=needs_mask,
            )

            self.import_in_progress = True

            # We need to disable all intensity corrections during import.
            # Users can just re-enable them if they are needed.
            HexrdConfig().disable_all_intensity_corrections()

            HexrdConfig().set_image_mode_widget_tab.emit(ViewType.raw)
            HexrdConfig().enable_image_mode_widget.emit(False)
            HexrdConfig().enable_canvas_toolbar.emit(False)

            self.load_instrument_config()
            self.update_config_selection(self.ui.config_selection.currentIndex())
            self.enable_widgets(self.ui.config, self.ui.finalize, enabled=True)

            self.ui.config_file_label.setToolTip(
                'Defaults to currently loaded configuration'
            )
            self.ui.bbox.setToolTip('')
            if self.instrument == 'TARDIS':
                self.ui.bbox.setToolTip(
                    'The bounding box editors are not '
                    + 'available for the TARDIS instrument'
                )

            # Indicate that an instrument was selected so the main window can
            # update anything it needs to update.
            self.instrument_was_selected.emit()

    def set_convention(self):
        new_conv = {'axes_order': 'zxz', 'extrinsic': False}
        HexrdConfig().set_euler_angle_convention(new_conv)

    def update_config_selection(self, idx):
        enable_load = idx == 2  # Load configuration from file selected
        self.enable_widgets(
            self.ui.load_config, self.ui.config_file_label, enabled=enable_load
        )

        self.update_config_settings()
        if self.ui.instrument.isEnabled():
            self.get_instrument_defaults()

    @property
    def config_setting(self) -> str:
        return self.ui.config_settings.currentText()

    @property
    def has_config_settings(self):
        return bool(
            self.instrument
            and self.instrument.lower() == 'tardis'
            and
            # "Default configuration"
            self.ui.config_selection.currentIndex() == 0
        )

    @property
    def has_template(self):
        return self.it is not None and self.it.shape is not None

    def update_config_settings(self):
        label = self.ui.config_settings_label
        combo = self.ui.config_settings

        with block_signals(combo):
            enable = self.has_config_settings
            label.setVisible(enable)
            combo.setVisible(enable)
            if not enable:
                # Nothing more to do
                combo.clear()
                return

            # Only two settings we currently support are 1 XRS and 2 XRS for TARDIS
            # If there was a previous selection, keep that.
            prev = combo.currentText()
            combo.clear()

            options = [
                '1 XRS',
                '2 XRS',
            ]
            combo.addItems(options)
            if prev:
                combo.setCurrentText(prev)

    def load_atlas_coords(self):
        file, filter = QFileDialog.getOpenFileName(
            self.ui, 'Select coordinates file', dir=HexrdConfig().working_dir
        )
        if not file:
            return
        with open(file, 'r') as f:
            coords = yaml.safe_load(f)
        self.atlas_coords = {d: np.array(c) for d, c in coords.items()}
        self.ui.atlas_label.setText(Path(file).name)

    def load_instrument_config(self):
        temp = tempfile.NamedTemporaryFile(delete=False, suffix='.hexrd')
        self.config_file = temp.name
        HexrdConfig().save_instrument_config(self.config_file)
        fname = f'default_{self.instrument.lower()}_config.yml'
        with resource_loader.resource_path(hexrdgui.resources.calibration, fname) as f:
            for overlay in HexrdConfig().overlays:
                overlay.visible = False
            HexrdConfig().load_instrument_config(f, import_raw=True)

    def config_loaded_from_menu(self):
        if not self.import_in_progress:
            return
        self.load_instrument_config()

    def detector_selected(self, selected):
        # Don't allow the color map range to change while changing detectors.
        self.cmap.block_updates(True)
        try:
            self.ui.instrument.setDisabled(selected)
            self.detector = self.ui.detectors.currentText()
            self.current_image_selection = self.detector
            # If we have already loaded this detector's image, reload it
            if self.detector in self.completed:
                self.current_image_selection = self.detector
                # Find the data and dark files for this detector
                data_file = self.loaded_images[f'{self.detector} data']
                dark_file = self.loaded_images[f'{self.detector} dark']
                # Update the label text and tooltip
                self.ui.detector_files_label.setText(Path(data_file).stem)
                self.ui.detector_files_label.setToolTip(Path(data_file).stem)
                self.ui.dark_files_label.setText(Path(dark_file).stem)
                self.ui.dark_files_label.setToolTip(Path(dark_file).stem)
                # Reload the image
                self.manually_load_detector_images()
        finally:
            self.cmap.block_updates(False)

    @property
    def image_plate(self):
        return self._image_plate

    @image_plate.setter
    def image_plate(self, ip):
        self._image_plate = ip
        if self.it is not None:
            self.it.detector = ip

    def image_plate_selected(self, selected):
        # Don't allow the color map range to change while we are changing
        # image plates. Otherwise, it gets reset to something like "1 - 6".
        self.cmap.block_updates(True)
        try:
            self.ui.instrument.setDisabled(selected)
            self.image_plate = self.ui.image_plates.currentText()
            self.current_image_selection = self.image_plate
            # If we have already loaded this image plate's image, reload it
            if self.image_plate in self.edited_images:
                # Find the image plate file
                ip_file = self.loaded_images[self.image_plate]
                # Update the label text and tooltip
                if self.image_plate in self.loaded_images:
                    file_name = Path(self.loaded_images[self.image_plate]).stem
                    self.ui.image_plate_files_label.setText(file_name)
                    self.ui.image_plate_files_label.setToolTip(file_name)
                # Reload the image
                self.load_images(selected_file=ip_file)
                # Re-add the template with the saved position and mark complete
                self.add_template()
                self.complete_current_selection()
            else:
                self.add_template()
                if self.instrument == 'TARDIS':
                    self.cancel_workflow.emit()
                    self.enable_widgets(self.ui.accept_template, enabled=False)
                else:
                    self.enable_widgets(self.ui.accept_template, enabled=True)
        finally:
            self.cmap.block_updates(False)

    def update_bbox_height(self, val):
        y0, y1, *x = self.it.bounds
        h = y1 - y0
        scale = 1 - ((h - val) / h)
        self.it.scale_template(sy=scale)

    def update_bbox_width(self, val):
        *y, x0, x1 = self.it.bounds
        w = x1 - x0
        scale = 1 - ((w - val) / w)
        self.it.scale_template(sx=scale)

    def _set_transform(self):
        if self.instrument == 'FIDDLE':
            flip = LLNLTransform.FIDDLE
        if self.instrument == 'PXRDIP':
            flip = LLNLTransform.PXRDIP
        elif self.instrument == 'TARDIS':
            if self.image_plate == 'IMAGE-PLATE-2':
                flip = LLNLTransform.IP2
            elif self.image_plate == 'IMAGE-PLATE-3':
                flip = LLNLTransform.IP3
            elif self.image_plate == 'IMAGE-PLATE-4':
                flip = LLNLTransform.IP4
        HexrdConfig().load_panel_state['trans'] = [flip]

    def accept_detector(self, data_file, dark_file):
        # Custom dark subtraction for the FIDDLE instrument
        img = [[]] * FIDDLE_FRAMES
        first, last = '/'.join(FIDDLE_HDF5_PATH).rsplit('0', 1)
        for frame in range(FIDDLE_FRAMES):
            # Use known path to find data 0/1/2/3 paths
            path = f'{first}{frame}{last}'
            # Load in detector data and dark data for this frame
            with h5py.File(data_file) as data:
                data_raw = np.array(data[path])
            with h5py.File(dark_file) as dark:
                dark_raw = np.array(dark[path])
            # Apply dark subtraction for this frame only
            img[frame] = data_raw - dark_raw

        # Create an imageseries from the 4 processed frames
        ims = ImageFileManager().open_file(img)
        self.detector_images[self.detector]['img'] = ims
        self.complete_current_selection()

    def manually_load_detector_images(self):
        data_file = self.detector_images[self.detector]['data']
        dark_file = self.detector_images[self.detector]['dark']

        # Process each frame and create an imageseries
        self.accept_detector(data_file, dark_file)
        img = self.edited_images[self.detector]['img']

        # Load in the new imageseries
        HexrdConfig().imageseries_dict['default'] = img
        ImageLoadManager().read_data(ui_parent=self.ui.parent(), postprocess=True)

    def load_detector_images(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Select file(s)', dir=HexrdConfig().images_dir
        )
        if not selected_file:
            return
        HexrdConfig().set_images_dir(selected_file)

        # Make sure we're not transforming detector images
        HexrdConfig().load_panel_state['trans'] = [UI_TRANS_INDEX_NONE]

        # Needed to identify current image, regardless of image load path
        self.current_image_selection = self.detector

        # Use a custom dict for detector images to track loaded data and dark
        # files. Needed to make sure files are correctly associated when
        # manually loading each detector.
        self.detector_images.setdefault(self.detector, {})
        self.detector_images[self.detector].setdefault('data', None)
        self.detector_images[self.detector].setdefault('dark', None)

        # Try to automatically find missing data and dark files for this and
        # remaining detectors.
        file_name = Path(selected_file).stem
        if file_name.endswith('999'):
            self.ui.detector_files_label.setText(file_name)
            self.ui.detector_files_label.setToolTip(file_name)
            self.detector_images[self.detector]['data'] = selected_file
        else:
            self.ui.dark_files_label.setText(file_name)
            self.ui.dark_files_label.setToolTip(file_name)
            self.detector_images[self.detector]['dark'] = selected_file
        selected = self.detector_images[self.detector]

        # Create regex pattern to try to match data and dark images
        # ex:
        # TD_TC000-000_FIDDLE_CAMERA-02-DB_SHOT_RAW-FIDDLE-CAMERA_N240717-001-999.h5
        # ->
        # TD_TC000-000_FIDDLE_CAMERA-*-DB_SHOT_RAW-FIDDLE-CAMERA_N240717-001-*.h5
        image = re.sub(r"CAMERA-\d{2}-", "CAMERA-*-", selected_file)
        files = re.sub(r"-\d{3}.h", "-*.h", image)

        # Sort matched files. We know that those ending in -999 are data files.
        # Dark files may have different values at the end (-003, -005, etc.) so
        # we separate as data file (-999) and *not* data (anything else).
        matches = sorted(glob.glob(files))
        data_matches = [m for m in matches if m.endswith('-999.h5')]
        dark_matches = [m for m in matches if m not in data_matches]

        if len(data_matches) == len(dark_matches) == len(self.detectors):
            # All data and dark files have been found for all detectors
            original_det = self.detector
            for det in self.detectors:
                data = next((fname for fname in data_matches if det in fname))
                dark = next((fname for fname in dark_matches if det in fname))
                self.current_image_selection = self.detector = det
                self.detector_images.setdefault(self.detector, {})
                self.detector_images[self.detector]['data'] = data
                self.detector_images[self.detector]['dark'] = dark
                self.loaded_images[f'{self.detector} data'] = data
                self.loaded_images[f'{self.detector} dark'] = dark
                self.accept_detector(data, dark)
            self.detector = original_det
            # Update UI to reflect selected & found files
            self.ui.detector_files_label.setText(
                Path(self.detector_images[self.detector]['data']).stem
            )
            self.ui.detector_files_label.setToolTip(
                Path(self.detector_images[self.detector]['data']).stem
            )
            self.ui.dark_files_label.setText(
                Path(self.detector_images[self.detector]['dark']).stem
            )
            self.ui.dark_files_label.setToolTip(
                Path(self.detector_images[self.detector]['dark']).stem
            )
            self.current_image_selection = self.detector
            img = self.edited_images[self.detector]['img']
            HexrdConfig().imageseries_dict['default'] = img
            ImageLoadManager().read_data(ui_parent=self.ui.parent(), postprocess=True)
        else:
            # We couldn't find all of the matches. Enable manually matching and
            # loading all files for each detector.
            self.enable_widgets(
                self.ui.accept_detector,
                enabled=bool(selected['data'] and selected['dark']),
            )

    def load_images(self, checked=False, selected_file=None):
        # Needed to identify current image, regardless of image load path
        self.current_image_selection = self.image_plate

        self._set_transform()

        if selected_file is None:
            caption = 'Select file(s)'
            selected_file, selected_filter = QFileDialog.getOpenFileName(
                self.ui, caption, dir=HexrdConfig().images_dir
            )

        if selected_file:
            self.loaded_images[self.image_plate] = selected_file
            HexrdConfig().set_images_dir(selected_file)

            files, manual = ImageLoadManager().load_images([selected_file])

            # If it is a hdf5 file allow the user to select the path
            ext = os.path.splitext(selected_file)[1]
            if ImageFileManager().is_hdf(
                ext
            ) and not ImageFileManager().hdf_path_exists(selected_file):
                path_selected = ImageFileManager().path_prompt(selected_file)
                if not path_selected:
                    return

            for raw_axes in self.canvas.raw_axes.values():
                if not raw_axes.get_autoscale_on():
                    raw_axes.set_autoscale_on(True)

            # The ImageLoadManager parent needs to be set to the main window
            # because when set to the ui (QDockWidget) the dock widget is
            # closed after accepting the image selection. We're not positive
            # why this is the case but it may be related to being a parent to
            # the QProgressDialog.
            ImageLoadManager().read_data(files, ui_parent=self.ui.parent())
            self.it = InteractiveTemplate(
                self.canvas, self.image_plate, instrument=self.instrument
            )
            # We should be able to immediately interact with the template
            self.it.static_mode = False

            file_names = [os.path.split(f[0])[1] for f in files]
            self.ui.image_plate_files_label.setText(', '.join(file_names))
            self.ui.image_plate_files_label.setToolTip(', '.join(file_names))
            self.enable_widgets(
                self.ui.add_transform,
                self.ui.finalize,
                self.ui.image_plates,
                self.ui.image_plate_label,
                self.ui.accept_template,
                enabled=True,
            )
            self.enable_widgets(
                self.ui.data, self.ui.detector_load, self.ui.dark_load, enabled=False
            )
            self.add_template()

    def add_transform(self):
        # Prevent color map reset on transform
        self.cmap.block_updates(True)
        self.it.toggle_boundaries(show=False)
        ilm = ImageLoadManager()
        ilm.set_state({'trans': [self.ui.transforms.currentIndex()]})
        ilm.begin_processing(postprocess=True)
        self.cmap.block_updates(False)

        self.ui.transforms.setCurrentIndex(0)

        img = HexrdConfig().image('default', 0)
        if self.image_plate in self.edited_images.keys():
            # This transform is being done post-processing
            self.edited_images[self.image_plate]['img'] = img
            self.edited_images[self.image_plate]['height'] = img.shape[0]
            self.edited_images[self.image_plate]['width'] = img.shape[1]

        self.it.toggle_boundaries(show=True)
        if self.has_template:
            self.it.update_image(img)

    def display_bounds(self):
        self.ui.bb_height.blockSignals(True)
        self.ui.bb_width.blockSignals(True)

        y0, y1, x0, x1 = self.it.bounds
        self.ui.bb_width.setMaximum(self.it.img.shape[1])
        self.ui.bb_height.setMaximum(self.it.img.shape[0])

        self.ui.bb_width.setValue(x1)
        self.ui.bb_height.setValue(y1)

        self.ui.bb_height.blockSignals(False)
        self.ui.bb_width.blockSignals(False)

    def read_in_template_bounds(self, module, file_name):
        with resource_loader.resource_path(module, file_name) as f:
            data = np.loadtxt(f)
        panels = create_hedm_instrument().detectors
        verts = panels['default'].cartToPixel(data)
        verts[:, [0, 1]] = verts[:, [1, 0]]
        return verts

    def add_template(self):
        if (
            self.it is None  # InteractiveTemplate was never initialized
            or self.instrument is None  # No instrument selected
            or not self.image_plate  # No image plate to associate template with
        ):
            return

        if self.it.complete and self.instrument != 'PXRDIP':
            # For the TARDIS and FIDDLE use case only one template is applied
            # per image. Only add a new template if the image plate has not
            # been completed or this is a single image use-case
            # (i.e. PXRDIP, BBXRD).
            return

        self.it.clear()
        verts = self.read_in_template_bounds(
            module=hexrd_resources,
            file_name=f'{self.instrument}_{self.image_plate}_bnd.txt',
        )
        kwargs = {'fill': False, 'lw': 1, 'linestyle': '-'}
        self.it.create_polygon(verts, **kwargs)
        self.it.update_image(HexrdConfig().image('default', 0))
        self.update_template_style()

        self.display_bounds()
        self.enable_widgets(
            self.ui.outline_appearance, self.ui.template_instructions, enabled=True
        )
        if self.ui.instruments.currentText() != 'TARDIS':
            self.ui.bbox.setEnabled(True)

    def update_template_style(self):
        ls = self.ui.line_style.currentText()
        lw = self.ui.line_size.value()
        self.it.update_style(ls, lw, self.outline_color)

    def pick_line_color(self):
        sender = self.sender()
        color = sender.text()

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec():
            sender.setText(dialog.selectedColor().name())
            lc = self.ui.line_color
            lc.setStyleSheet('QPushButton {background-color: %s}' % lc.text())
            self.outline_color = dialog.selectedColor().name()
            self.update_template_style()

    def setup_translate_rotate(self):
        if self.has_template:
            self.it.disconnect()
            self.it.connect_translate_rotate()

    def clear_boundry(self):
        if self.has_template:
            self.it.clear()

    def save_boundary_position(self):
        position = {'angle': self.it.rotation, 'translation': self.it.translation}
        HexrdConfig().set_boundary_position(self.instrument, self.image_plate, position)
        if self.it.shape:
            self.it.save_boundary(self.outline_color)

    def swap_bounds_for_cropped(self):
        self.it.clear()
        line, width, color = self.it.shape_styles[-1].values()
        verts = self.read_in_template_bounds(
            module=hexrd_resources, file_name=f'TARDIS_IMAGE-PLATE-3_bnd_cropped.txt'
        )
        kwargs = {'fill': False, 'lw': width, 'color': color, 'linestyle': '--'}
        self.it.create_polygon(verts, **kwargs)
        self.update_bbox_width(1330)
        self.update_bbox_height(238)

    def complete_current_selection(self):
        if self.has_template:
            self.save_boundary_position()
            if self.image_plate == 'IMAGE-PLATE-3':
                self.swap_bounds_for_cropped()
        self.finalize()
        self.completed.append(self.current_image_selection)
        self.enable_widgets(
            self.ui.file_selection,
            self.ui.add_transform,
            self.ui.complete,
            self.ui.detector_load,
            self.ui.dark_load,
            enabled=True,
        )
        self.enable_widgets(
            self.ui.outline_appearance,
            self.ui.template_instructions,
            self.ui.accept_template,
            self.ui.add_transform,
            self.ui.accept_detector,
            enabled=False,
        )
        self.set_widget_visibility(self.ui.completed_dets_and_ips, visible=True)
        if self.instrument == 'PXRDIP':
            shared_file = next(iter(self.loaded_images.values()))
            self.loaded_images[self.current_image_selection] = shared_file
        loaded = [
            f'{d}: {Path(self.loaded_images[d]).stem}'
            for d in sorted(self.loaded_images)
        ]
        text = '\n'.join(loaded)
        self.ui.completed_text.setText(text)
        self.ui.completed_text.setToolTip(text)

    def finalize(self):
        detectors = self.ip_and_det_defaults['default_config'].get('detectors', {})
        det = detectors.setdefault(self.current_image_selection, {})
        width = det.setdefault('pixels', {}).get('columns', 0)
        height = det.setdefault('pixels', {}).get('rows', 0)
        panel_buffer = [0.0, 0.0]
        tilt = 0.0

        if not self.has_template:
            img = self.detector_images[self.detector]['img']
        else:
            if self.instrument == 'PXRDIP':
                # Boundary is currently rotated 90 degrees
                width, height = height, width
            self.it.cropped_image(height, width)

            img, panel_buffer = self.it.masked_image
            if self.instrument == 'PXRDIP':
                # !!! need to rotate buffers
                panel_buffer = panel_buffer.T[::-1, :]
            tilt = self.it.rotation
            self.it.completed()

        self.edited_images[self.current_image_selection] = {
            'img': img,
            'tilt': tilt,
            'panel_buffer': panel_buffer,
        }

    def clear(self):
        self.clear_boundry()
        self.enable_widgets(self.ui.add_transform, self.ui.file_selection, enabled=True)
        self.enable_widgets(
            self.ui.outline_appearance, self.ui.template_instructions, enabled=False
        )

    def check_for_unsaved_changes(self):
        if not self.has_template and self.current_image_selection in self.completed:
            return

        msg = (
            'The currently selected image plate has changes that have not'
            + ' been accepted. Keep changes?'
        )
        response = QMessageBox.question(
            self.ui, 'HEXRD', msg, (QMessageBox.Cancel | QMessageBox.Save)
        )
        if response == QMessageBox.Save:
            self.complete_current_selection()

    def reset_panel(self):
        # Remove any templates that exist
        self.clear_boundry()
        # Reset internal state
        self.completed = []
        self.atlas_coords = None
        self.defaults.clear()
        self.config_file = None
        self.import_in_progress = False
        self.loaded_images.clear()
        self.edited_images.clear()
        # Reset all UI values that are populated during import
        self.ui.image_plates.setCurrentIndex(0)
        self.ui.detectors.setCurrentIndex(0)
        self.ui.image_plate_files_label.setText('')
        self.ui.image_plate_files_label.setToolTip('')
        self.ui.detector_files_label.setText('')
        self.ui.detector_files_label.setToolTip('')
        self.ui.dark_files_label.setText('')
        self.ui.dark_files_label.setToolTip('')
        self.ui.completed_text.setText('')
        self.ui.completed_text.setToolTip('')
        not_default = self.ui.config_selection.currentIndex() != 0
        self.ui.load_config.setEnabled(not_default)
        self.ui.config_file_label.setEnabled(not_default)
        self.ui.config_file_label.setText('No File Selected')
        self.ui.config_file_label.setToolTip(
            'Defaults to currently loaded configuration'
        )
        self.ui.atlas_label.setText('No File Selected')
        # Reset widget states - disable/enable/show/hide as appropriate
        self.enable_widgets(
            self.ui.image_plate_raw_image,
            self.ui.config,
            self.ui.add_transform,
            self.ui.outline_appearance,
            self.ui.finalize,
            self.ui.load_config,
            self.ui.config_file_label,
            self.ui.template_instructions,
            self.ui.accept_detector,
            enabled=False,
        )
        self.enable_widgets(self.ui.data, self.ui.file_selection, enabled=True)
        self.set_widget_visibility(
            self.ui.image_plate_raw_image,
            self.ui.template_instructions,
            self.ui.outline_appearance,
            self.ui.detector_raw_image,
            self.ui.instr_settings_label,
            self.ui.instr_settings,
            self.ui.load_atlas,
            self.ui.atlas_label,
            visible=False,
        )
        # We're all reset and ready to re-enable the main UI features
        HexrdConfig().enable_image_mode_widget.emit(True)

    def import_complete(self):
        self.import_in_progress = False
        self.cmap.block_updates(True)
        self.check_for_unsaved_changes()

        detectors = self.ip_and_det_defaults['default_config'].setdefault(
            'detectors', {}
        )
        not_set = [d for d in detectors if d not in self.completed]
        for det in not_set:
            del self.ip_and_det_defaults['default_config']['detectors'][det]

        instr = HEDMInstrument(
            instrument_config=self.ip_and_det_defaults['default_config']
        )

        if self.atlas_coords is not None:
            atlas_config = AtlasConfig(self.atlas_coords, instr)
            for detector in self.detectors:
                atlas_config.update_instrument(detector)

        for det in self.completed:
            panel = instr.detectors[det]
            # first need the zxz Euler angles from the panel rotation matrix.
            *zx, z = angles_from_rmat_zxz(panel.rmat)
            # convert updated zxz angles to rmat
            # !!! JVB verified that the rotation is stored with + as clockwise;
            #     hence, the modification of z stays as '+'. Our convention has
            #     '+' as counter-clockwise, but the detector rotation is the
            #     inverse of the image rotation...  so '+' is already inverted.
            tilts = [*zx, (z + float(self.edited_images[det]['tilt']))]
            rmat_updated = make_rmat_euler(tilts, 'zxz', extrinsic=False)
            # convert to angle-axis parameters
            rang, raxs = angleAxisOfRotMat(rmat_updated)
            # update tilt property on panel
            panel.tilt = rang * raxs.flatten()

        temp = tempfile.NamedTemporaryFile(delete=False, suffix='.hexrd')
        try:
            instr.write_config(temp.name, style='hdf5')
            HexrdConfig().load_instrument_config(temp.name)
        finally:
            temp.close()
            Path(temp.name).unlink()

        self.set_convention()
        if self.instrument == 'PXRDIP':
            HexrdConfig().load_panel_state['trans'] = [UI_TRANS_INDEX_ROTATE_90] * len(
                self.image_plates
            )

        det_names = HexrdConfig().detector_names
        files = []
        for det in det_names:
            img = self.edited_images[det]['img']
            if self.instrument == 'FIDDLE' and det in self.image_plates:
                img = np.asarray([img] * FIDDLE_FRAMES)
            files.append([img])
        # The ImageLoadManager parent needs to be set to the main window
        # because when set to the ui (QDockWidget) the dock widget is
        # closed after accepting the image selection. We're not positive
        # why this is the case but it may be related to being a parent to
        # the QProgressDialog.
        ImageLoadManager().read_data(files, ui_parent=self.ui.parent())

        for det in det_names:
            det_config = HexrdConfig().config['instrument']['detectors'][det]
            det_config['buffer'] = self.edited_images[det]['panel_buffer']

        HexrdConfig().recent_images = list(self.loaded_images.values())

        self.close_widget()
        self.ui.instrument.setDisabled(False)
        HexrdConfig().enable_canvas_toolbar.emit(True)
        self.cmap.block_updates(False)

        # If this is a FIDDLE instrument users will be prompted to set (or not)
        # the median filter after the import is complete
        self.complete_workflow.emit(self.instrument == 'FIDDLE')

    def show(self):
        self.ui.show()

    def close_widget(self):
        block_list = [self.ui.instruments, self.ui.image_plates]
        with block_signals(*block_list):
            self.ui.instruments.setCurrentIndex(0)
            self.reset_panel()
        if self.ui.isFloating():
            self.ui.close()

    def on_canceled(self):
        self.close_widget()
        self.cancel_workflow.emit()
