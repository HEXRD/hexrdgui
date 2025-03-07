from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox, QInputDialog, QLineEdit, QMessageBox, QPushButton
)

import numpy as np
import yaml

from hexrd.resources import detector_templates
from hexrd.instrument import calc_angles_from_beam_vec, calc_beam_vec
from hexrd.transforms import xfcapi

from hexrdgui import constants, resource_loader
from hexrdgui.calibration.panel_buffer_dialog import PanelBufferDialog
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals, unique_name
from hexrdgui.xray_energy_selection_dialog import XRayEnergySelectionDialog


class InstrumentFormViewWidget(QObject):

    """Emitted when GUI data has changed"""
    gui_data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.cfg = HexrdConfig()

        loader = UiLoader()
        self.ui = loader.load_file('instrument_form_view_widget.ui', parent)

        # Make sure the stacked widget starts at 0
        self.ui.beam_vector_input_stacked_widget.setCurrentIndex(0)
        self.update_cartesian_beam_vector_normalized_note()

        self.detector_widgets_disabled = False

        # Turn off autocomplete for the QComboBox
        self.ui.cal_det_current.setCompleter(None)

        self.setup_connections()

        self.timer = None

    def setup_connections(self):
        self.ui.cal_det_current.installEventFilter(self)
        self.ui.cal_energy.valueChanged.connect(self.on_energy_changed)
        self.ui.cal_energy_wavelength.valueChanged.connect(
            self.on_energy_wavelength_changed)
        self.ui.xray_energies_table.pressed.connect(
            self.open_xray_energies_dialog)

        self.ui.cal_det_current.currentIndexChanged.connect(
            self.on_detector_changed)
        self.ui.cal_det_current.lineEdit().editingFinished.connect(
            self.on_detector_name_edited)
        self.ui.cal_det_remove.clicked.connect(self.on_detector_remove_clicked)
        self.ui.cal_det_add.clicked.connect(self.on_detector_add_clicked)

        all_widgets = self.get_all_widgets()
        skip_widgets = ['cal_det_current', 'cal_det_add', 'cal_det_remove']
        for widget in all_widgets:
            if widget.objectName() in skip_widgets:
                continue

            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self.update_config_from_gui)
            elif isinstance(widget, QLineEdit):
                widget.textEdited.connect(self.update_config_from_gui)
            elif isinstance(widget, QPushButton):
                widget.pressed.connect(self.update_config_from_gui)
            else:
                widget.valueChanged.connect(self.update_config_from_gui)
                widget.valueChanged.connect(self.gui_value_changed)

        self.ui.cal_det_function.currentIndexChanged.connect(
            self.update_gui_from_config)
        self.ui.cal_det_buffer.clicked.connect(self._on_configure_buffer)

        self.ui.beam_vector_input_stacked_widget.currentChanged.connect(
            self.update_cartesian_beam_vector)

        for w in self.cartesian_beam_vector_widgets:
            w.valueChanged.connect(self.cartesian_beam_vector_modified)

        self.ui.beam_vector_is_finite.toggled.connect(
            self.set_beam_vector_is_finite)
        self.ui.beam_vector_magnitude.valueChanged.connect(
            self.beam_vector_magnitude_value_changed)
        self.ui.cartesian_beam_vector_convention.currentIndexChanged.connect(
            self.cartesian_beam_vector_convention_changed)

    def on_energy_changed(self):
        val = self.ui.cal_energy.value()

        # Make sure energy has same style
        kev_widget = getattr(self.ui, 'cal_energy')
        wave_widget = getattr(self.ui, 'cal_energy_wavelength')
        wave_widget.setStyleSheet(kev_widget.styleSheet())

        block_signals = self.ui.cal_energy_wavelength.blockSignals(True)
        try:
            new_wavelength = constants.KEV_TO_WAVELENGTH / val
            self.ui.cal_energy_wavelength.setValue(new_wavelength)
        finally:
            self.ui.cal_energy_wavelength.blockSignals(block_signals)

    def on_energy_wavelength_changed(self):
        val = self.ui.cal_energy_wavelength.value()

        block_signals = self.ui.cal_energy.blockSignals(True)
        try:
            new_energy = constants.WAVELENGTH_TO_KEV / val
            self.ui.cal_energy.setValue(new_energy)
        finally:
            self.ui.cal_energy.blockSignals(block_signals)

    def open_xray_energies_dialog(self):
        dialog = XRayEnergySelectionDialog(self.ui)
        if not dialog.exec():
            return

        # The table has units in eV. Convert to keV.
        self.ui.cal_energy.setValue(dialog.selected_energy / 1e3)

    def on_detector_changed(self):
        self.update_detector_from_config()

    def enable_detector_widgets(self, enable=True):
        detector_widgets = self.cfg.get_detector_widgets()
        detector_widgets.remove('cal_det_add')
        for widget in detector_widgets:
            gui_widget = getattr(self.ui, widget)
            gui_widget.setEnabled(enable)

        self.detector_widgets_disabled = not enable

    def on_detector_name_edited(self):
        new_name = self.ui.cal_det_current.currentText()
        detector_names = self.cfg.detector_names

        # Ignore it if there is already a detector with this name
        if new_name in detector_names:
            return

        # Get the old name from the underlying item
        idx = self.ui.cal_det_current.currentIndex()
        old_name = self.ui.cal_det_current.itemText(idx)

        self.ui.cal_det_current.setItemText(idx, new_name)
        self.cfg.rename_detector(old_name, new_name)

    def on_detector_remove_clicked(self):
        if self.ui.cal_det_current.count() <= 1:
            msg = 'Cannot remove last detector'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            return

        current_detector = self.get_current_detector()
        idx = self.ui.cal_det_current.currentIndex()

        self.cfg.remove_detector(current_detector)
        if idx > 0:
            self.ui.cal_det_current.setCurrentIndex(idx - 1)
        else:
            self.update_detector_from_config()

    def on_detector_add_clicked(self):
        # Grab current selection info
        combo = self.ui.cal_det_current
        current_detector = self.get_current_detector()

        # Create a dict of options for adding a detector, mapping name to
        # imported detector config (or None for copying from currently
        # selected detector)
        options = {f'Copy {current_detector}': None}
        for f in resource_loader.module_contents(detector_templates):
            if f.endswith(('.yml', '.yaml')):
                det = resource_loader.load_resource(detector_templates, f)
                if default := yaml.safe_load(det):
                    name = next(iter(default))
                    options[name] = default[name]

        # Provide simple dialog for selecting detector to import/copy
        msg = 'Copy current or select template'
        det_name, ok = QInputDialog.getItem(
            self.ui, 'Add New Detector', msg, list(options), 0, False)

        if not ok:
            return

        if (new_det := options.get(det_name)) is None:
            new_detector_name = f'Copy of {current_detector}'
        else:
            new_detector_name = det_name

            if 'transform' not in new_det:
                # Add in the default transform
                transform = HexrdConfig().default_detector['transform']
                new_det['transform'] = transform

        # Ensure it is unique
        new_detector_name = unique_name(HexrdConfig().detector_names,
                                        new_detector_name)

        # Add the imported or copied detector and update current selection
        self.cfg.add_detector(new_detector_name, current_detector, new_det)

        self.update_detector_from_config()

        # Set the current detector to be the newly added one
        new_ind = combo.findText(new_detector_name)
        combo.setCurrentIndex(new_ind)

    def update_config_from_gui(self):
        """This function only updates the sender value"""
        sender = self.sender()
        name = sender.objectName()
        if name == 'cal_energy_wavelength':
            # Need to update the `cal_energy` entry instead
            sender = self.ui.cal_energy
            name = sender.objectName()

        value = self._get_gui_value(sender)
        current_detector = self.get_current_detector()
        self.cfg.set_val_from_widget_name(name, value, current_detector)

    def gui_value_changed(self):
        """We only want to emit a changed signal once editing is done"""
        if self.timer is None:
            self.timer = QTimer()
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.gui_data_changed)

        # Start or restart our timer...
        self.timer.start(666)

    def update_gui_from_config(self):
        previously_blocked = self.block_all_signals()

        try:
            gui_yaml_paths = self.cfg.get_gui_yaml_paths()
            for var, path in gui_yaml_paths:
                if 'detector_name' in path:
                    # We give these special treatment
                    continue

                config_val = self.cfg.get_instrument_config_val(path)
                chi_path = ['oscillation_stage', 'chi']
                if path == chi_path:
                    # Display chi in degrees
                    config_val = np.degrees(config_val).item()

                gui_var = getattr(self.ui, var)
                self._set_gui_value(gui_var, config_val)
        finally:
            self.unblock_all_signals(previously_blocked)

        # Update the wavelength also
        self.on_energy_changed()

        self.update_detector_from_config()

        self.update_beam_vector_magnitude_from_config()

        if self.sender() not in self.cartesian_beam_vector_widgets:
            # If a cartesian beam vector widget did not trigger this update,
            # then update the cartesian beam vector widgets.
            self.update_cartesian_beam_vector()

    def update_detector_from_config(self):
        previously_blocked = self.block_all_signals()

        try:
            combo_widget = self.ui.cal_det_current
            detector_names = self.cfg.detector_names
            if not detector_names:
                # Disable detector widgets if there is no valid detector
                if not self.detector_widgets_disabled:
                    self.enable_detector_widgets(enable=False)

                return
            elif self.detector_widgets_disabled:
                # Enable detector widgets if they were previously disabled
                self.enable_detector_widgets(enable=True)

            cur_detector = detector_names[0]
            if combo_widget.currentText() in detector_names:
                cur_detector = combo_widget.currentText()

            gui_yaml_paths = self.cfg.get_gui_yaml_paths(['detectors',
                                                          'detector_name'])

            tilt_path = ['transform', 'tilt']
            dist_params_path = ['distortion', 'parameters']
            for var, path in gui_yaml_paths:
                if len(path) > 1 and path[:2] == dist_params_path:
                    # The distortion type should already be set before here
                    # Check for the number of params. If this is greater
                    # than the number of params, skip over it.
                    if not path[-1] < self.num_distortion_params:
                        continue

                gui_var = getattr(self.ui, var)
                full_path = ['detectors', cur_detector] + path
                config_val = self.cfg.get_instrument_config_val(full_path)

                if path[:-1] == tilt_path:
                    # Special treatment for tilt widgets
                    if HexrdConfig().rotation_matrix_euler() is None:
                        gui_var.setSuffix('')
                    else:
                        gui_var.setSuffix('°')
                        config_val = np.degrees(config_val).item()

                self._set_gui_value(gui_var, config_val)

            combo_items = []
            for i in range(combo_widget.count()):
                combo_items.append(combo_widget.itemText(i))

            if combo_items != detector_names:
                combo_widget.clear()
                combo_widget.addItems(detector_names)
                new_ind = combo_widget.findText(cur_detector)
                combo_widget.setCurrentIndex(new_ind)

        finally:
            self.unblock_all_signals(previously_blocked)

        # Update distortion parameter enable states
        self.update_distortion_params_enable_states()

    def get_current_detector(self):
        if self.detector_widgets_disabled:
            return None

        return self.ui.cal_det_current.currentText()

    def get_all_widgets(self):
        gui_yaml_paths = self.cfg.get_gui_yaml_paths()
        widgets = [x[0] for x in gui_yaml_paths]
        widgets += self.cfg.get_detector_widgets()
        widgets += ['cal_energy_wavelength']
        widgets = list(set(widgets))
        widgets = [getattr(self.ui, x) for x in widgets]
        return widgets

    def block_all_signals(self):
        previously_blocked = []
        all_widgets = self.get_all_widgets()

        for widget in all_widgets:
            previously_blocked.append(widget.blockSignals(True))

        return previously_blocked

    def unblock_all_signals(self, previously_blocked):
        all_widgets = self.get_all_widgets()

        for block, widget in zip(previously_blocked, all_widgets):
            widget.blockSignals(block)

    def _set_gui_value(self, gui_object, value):
        """This is for calling various set methods for GUI variables

        For instance, QComboBox will call "setCurrentText", while
        QSpinBox will call "setValue".
        """
        if isinstance(gui_object, QComboBox):
            gui_object.setCurrentText(value)
        else:
            # If it is anything else, just assume setValue()
            gui_object.setValue(value)

    def _get_gui_value(self, gui_object):
        """This is for calling various get methods for GUI variables

        For instance, QComboBox will call "currentText", while
        QSpinBox will call "value".
        """
        if isinstance(gui_object, QComboBox):
            return gui_object.currentText()
        else:
            # If it is anything else, just assume value()
            return gui_object.value()

    @property
    def distortion(self):
        return self.ui.cal_det_function.currentText()

    @property
    def num_distortion_params(self):
        return HexrdConfig.num_distortion_parameters(self.distortion)

    def update_distortion_params_enable_states(self):
        num_params = self.num_distortion_params
        label_enabled = (num_params != 0)

        self.ui.distortion_parameters_label.setEnabled(label_enabled)
        self.ui.distortion_parameters_label.setVisible(label_enabled)

        base_str = 'cal_det_param_'
        for i in range(1000):
            widget_name = base_str + str(i)
            if not hasattr(self.ui, widget_name):
                break

            widget = getattr(self.ui, widget_name)
            enable = (num_params > i)
            widget.setEnabled(enable)
            widget.setVisible(enable)

    def eventFilter(self, target, event):
        # Unfortunately, when a user modifies the name in the editable
        # QComboBox 'cal_det_current', and then they press enter, it does
        # not emit QLineEdit.editingFinished(), but instead emits
        # QComboBox.currentIndexChanged(). This behavior is a little odd.
        # We need QLineEdit.editingFinished() so that the name gets updated.
        # If we call QLineEdit.editingFinished() here explicitly, it gets
        # emitted twice: once in this function, and once when the focus
        # gets cleared. Rather than calling it twice, let's just clear the
        # focus here so it gets called only once.
        if type(target) == QComboBox:
            if target.objectName() == 'cal_det_current':
                enter_keys = [Qt.Key_Return, Qt.Key_Enter]
                if type(event) == QKeyEvent and event.key() in enter_keys:
                    widget = self.ui.cal_det_current
                    widget.lineEdit().clearFocus()
                    return True

                if type(event) == QFocusEvent and event.lostFocus():
                    # This happens either if enter is pressed, or if the
                    # user tabs out.
                    widget = self.ui.cal_det_current
                    items = [widget.itemText(i) for i in range(widget.count())]
                    text = widget.currentText()
                    idx = widget.currentIndex()
                    if text in items and widget.itemText(idx) != text:
                        # Prevent the QComboBox from automatically changing
                        # the index to be that of the other item in the list.
                        # This is confusing behavior, and it's not what we
                        # want here.
                        widget.setCurrentIndex(idx)
                        # Let the widget lose focus
                        return False

        return False

    def _on_configure_buffer(self):
        # Disable button to prevent multiple dialogs
        self.ui.cal_det_buffer.setEnabled(False)
        detector = self.get_current_detector()
        dialog = PanelBufferDialog(detector, self.ui)
        dialog.show()
        # Re-enable button
        dialog.ui.finished.connect(
            lambda _: self.ui.cal_det_buffer.setEnabled(True))

    @property
    def active_beam(self):
        return HexrdConfig().active_beam

    @property
    def polar_beam_vector(self):
        beam_vector = self.active_beam['vector']
        return (
            beam_vector['azimuth'],
            beam_vector['polar_angle'],
        )

    @polar_beam_vector.setter
    def polar_beam_vector(self, v):
        beam_vector = self.active_beam['vector']

        any_modified = False

        if beam_vector['azimuth'] != v[0]:
            beam_vector['azimuth'] = v[0]
            any_modified = True

        if beam_vector['polar_angle'] != v[1]:
            beam_vector['polar_angle'] = v[1]
            any_modified = True

        self.update_gui_from_config()

        if any_modified:
            HexrdConfig().beam_vector_changed.emit()

    @property
    def cartesian_beam_vector_widgets(self):
        axes = ('x', 'y', 'z')
        return [getattr(self.ui, f'beam_vector_cartesian_{ax}')
                for ax in axes]

    def update_cartesian_beam_vector(self):
        self.cartesian_beam_vector = calc_beam_vec(*self.polar_beam_vector)
        self.update_cartesian_beam_vector_from_magnitude()
        self.update_cartesian_beam_vector_normalized_note()

    def update_cartesian_beam_vector_normalized_note(self):
        w = self.ui.cartesian_beam_vector_normalized_note
        w.setVisible(False)

        if self.ui.beam_vector_input_type.currentText() != 'Cartesian':
            # Only show the note for cartesian input
            return

        if self.beam_vector_is_finite:
            # Don't normalize the vector if it is finite
            return

        # Only add the note it if is not close to its unit vector
        beam_vec = np.asarray(self.cartesian_beam_vector)
        unit_vec = xfcapi.unitRowVector(beam_vec)

        if np.all(np.isclose(unit_vec, beam_vec, atol=1e-3)):
            return

        # Avoid displaying -0
        unit_vec = [0 if np.isclose(x, 0) else x for x in unit_vec]

        # Reverse the sign if we are using x-ray source
        sign = self.cartesian_beam_convention_sign

        w.setVisible(True)
        values_str = ', '.join([f'{x * sign:0.3f}' for x in unit_vec])
        text = f'Note: normalized to ({values_str})'
        w.setText(text)

    @property
    def cartesian_beam_vector(self):
        sign = self.cartesian_beam_convention_sign
        return [w.value() * sign for w in self.cartesian_beam_vector_widgets]

    @cartesian_beam_vector.setter
    def cartesian_beam_vector(self, v):
        sign = self.cartesian_beam_convention_sign
        widgets = self.cartesian_beam_vector_widgets
        with block_signals(*widgets):
            for i, w in enumerate(widgets):
                # This is to avoid "-0" from being displayed
                value = 0 if np.isclose(v[i], 0) else v[i]
                w.setValue(value * sign)

    def cartesian_beam_vector_modified(self):
        # Convert to polar
        self.polar_beam_vector = calc_angles_from_beam_vec(
            self.cartesian_beam_vector)
        self.update_beam_magnitude_from_cartesian()
        self.update_cartesian_beam_vector_normalized_note()

    def update_beam_magnitude_from_cartesian(self):
        if not self.beam_vector_is_finite:
            # If the beam vector is infinite, just return
            return

        beam_vec = np.atleast_2d(self.cartesian_beam_vector)
        self.beam_vector_magnitude = xfcapi.rowNorm(beam_vec).item()

    def update_cartesian_beam_vector_from_magnitude(self):
        if not self.beam_vector_is_finite:
            # If the beam vector is infinite, just return
            return

        beam_vec = calc_beam_vec(*self.polar_beam_vector)
        beam_vec *= self.beam_vector_magnitude
        self.cartesian_beam_vector = beam_vec

    @property
    def beam_vector_is_finite(self):
        return self.ui.beam_vector_is_finite.isChecked()

    @beam_vector_is_finite.setter
    def beam_vector_is_finite(self, b):
        self.ui.beam_vector_is_finite.setChecked(b)

    def set_beam_vector_is_finite(self, b):
        self.beam_vector_is_finite = b

        # Update the config
        v = self.beam_vector_magnitude
        beam_config = self.active_beam
        if beam_config['source_distance'] != v:
            beam_config['source_distance'] = v
            HexrdConfig().beam_vector_changed.emit()

        if self.ui.beam_vector_input_type.currentText() == 'Cartesian':
            self.update_beam_magnitude_from_cartesian()

        self.update_cartesian_beam_vector_normalized_note()

    @property
    def beam_vector_magnitude(self):
        if not self.beam_vector_is_finite:
            return np.inf

        return self.ui.beam_vector_magnitude.value()

    @beam_vector_magnitude.setter
    def beam_vector_magnitude(self, v):
        is_finite = v is not None and v != np.inf
        self.beam_vector_is_finite = is_finite

        if is_finite:
            self.ui.beam_vector_magnitude.setValue(v)

    def beam_vector_magnitude_value_changed(self, v):
        if not self.beam_vector_is_finite:
            # Don't do anything
            return

        self.beam_vector_magnitude = v

        # Update the config
        beam_config = self.active_beam
        if beam_config['source_distance'] != v:
            beam_config['source_distance'] = v
            HexrdConfig().beam_vector_changed.emit()

        # Update the cartesian vector
        self.update_cartesian_beam_vector_from_magnitude()

    def update_beam_vector_magnitude_from_config(self):
        beam_config = self.active_beam
        self.beam_vector_magnitude = beam_config['source_distance']

    @property
    def cartesian_beam_vector_convention(self):
        return self.ui.cartesian_beam_vector_convention.currentText()

    @cartesian_beam_vector_convention.setter
    def cartesian_beam_vector_convention(self, text):
        self.ui.cartesian_beam_vector_convention.setCurrentText(text)

    @property
    def cartesian_beam_convention_sign(self):
        convention = self.cartesian_beam_vector_convention
        signs = {
            'X-Ray Source': -1,
            'Propagation': 1,
        }
        if convention not in signs:
            raise Exception(f'Unhandled beam convention: {convention}')

        return signs[convention]

    def cartesian_beam_vector_convention_changed(self):
        widgets = self.cartesian_beam_vector_widgets
        with block_signals(*widgets):
            for w in widgets:
                # For now, just assume this means we toggle the sign
                w.setValue(w.value() * -1)

        self.update_cartesian_beam_vector_normalized_note()
