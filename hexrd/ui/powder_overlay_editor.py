import copy

import numpy as np

from PySide2.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QMessageBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.reflections_table import ReflectionsTable
from hexrd.ui.select_items_widget import SelectItemsWidget
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


class PowderOverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('powder_overlay_editor.ui', parent)

        self._overlay = None

        self.refinements_selector = SelectItemsWidget([], self.ui)
        self.ui.refinements_selector_layout.addWidget(
            self.refinements_selector.ui)

        self.setup_connections()

    def setup_connections(self):
        for w in self.widgets:
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self.update_config)

        self.ui.enable_width.toggled.connect(self.update_enable_states)
        self.refinements_selector.selection_changed.connect(
            self.update_refinements)

        self.ui.reflections_table.pressed.connect(self.show_reflections_table)

        HexrdConfig().material_tth_width_modified.connect(
            self.material_tth_width_modified_externally)

        self.ui.distortion_type.currentIndexChanged.connect(
            self.distortion_type_changed)

    def update_refinement_options(self):
        if self.overlay is None:
            return

        self.refinements_with_labels = self.overlay.refinements_with_labels

    @property
    def refinements(self):
        return [x[1] for x in self.refinements_with_labels]

    @refinements.setter
    def refinements(self, v):
        if len(v) != len(self.refinements_with_labels):
            msg = (
                f'Mismatch in {len(v)=} and '
                f'{len(self.refinements_with_labels)=}'
            )
            raise Exception(msg)

        with_labels = self.refinements_with_labels
        for i in range(len(v)):
            with_labels[i] = (with_labels[i][0], v[i])

        self.refinements_with_labels = with_labels

    @property
    def refinements_with_labels(self):
        return self.refinements_selector.items

    @refinements_with_labels.setter
    def refinements_with_labels(self, v):
        self.refinements_selector.items = copy.deepcopy(v)
        self.refinements_selector.update_table()

    def update_refinements(self):
        self.overlay.refinements = self.refinements

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        self.update_gui()

    def update_enable_states(self):
        enable_width = self.ui.enable_width.isChecked()
        self.ui.tth_width.setEnabled(enable_width)

    def update_gui(self):
        if self.overlay is None:
            return

        with block_signals(*self.widgets):
            self.tth_width_gui = self.tth_width_config
            self.offset_gui = self.offset_config
            self.distortion_type_gui = self.distortion_type_config
            self.distortion_kwargs_gui = self.distortion_kwargs_config
            self.refinements_with_labels = self.overlay.refinements_with_labels

            self.update_enable_states()
            self.update_reflections_table()

    def update_config(self):
        self.tth_width_config = self.tth_width_gui
        self.offset_config = self.offset_gui
        self.distortion_type_config = self.distortion_type_gui
        self.distortion_kwargs_config = self.distortion_kwargs_gui

        self.overlay.update_needed = True
        HexrdConfig().overlay_config_changed.emit()

    @property
    def material(self):
        return self.overlay.material if self.overlay is not None else None

    @property
    def tth_width_config(self):
        if self.overlay is None:
            return None

        return self.material.planeData.tThWidth

    @tth_width_config.setter
    def tth_width_config(self, v):
        if self.overlay is None:
            return

        self.material.planeData.tThWidth = v

        # All overlays that use this material will be affected
        HexrdConfig().flag_overlay_updates_for_material(self.material.name)

    @property
    def tth_width_gui(self):
        if not self.ui.enable_width.isChecked():
            return None
        return np.radians(self.ui.tth_width.value())

    @tth_width_gui.setter
    def tth_width_gui(self, v):
        enable_width = v is not None
        self.ui.enable_width.setChecked(enable_width)
        if enable_width:
            self.ui.tth_width.setValue(np.degrees(v))

    @property
    def offset_config(self):
        if self.overlay is None:
            return

        return self.overlay.tvec

    @offset_config.setter
    def offset_config(self, v):
        if self.overlay is None:
            return

        self.overlay.tvec = v

    @property
    def offset_gui(self):
        return [w.value() for w in self.offset_widgets]

    @offset_gui.setter
    def offset_gui(self, v):
        if v is None:
            return

        for i, w in enumerate(self.offset_widgets):
            w.setValue(v[i])

    @property
    def distortion_type_config(self):
        if self.overlay is None:
            return None

        return self.overlay.tth_distortion_type

    @distortion_type_config.setter
    def distortion_type_config(self, v):
        if self.overlay is None:
            return

        if self.overlay.tth_distortion_type == v:
            return

        self.overlay.tth_distortion_type = v
        HexrdConfig().overlay_distortions_modified.emit(self.overlay.name)

    @property
    def distortion_type_gui(self):
        if self.ui.distortion_type.currentText() == 'Offset':
            return None

        v = self.ui.pinhole_correction_type.currentText()

        conversions = {
            'Sample Layer': 'SampleLayerDistortion',
            'Pinhole': 'PinholeDistortion',
        }
        if v in conversions:
            v = conversions[v]

        return v

    @distortion_type_gui.setter
    def distortion_type_gui(self, v):
        widgets = [self.ui.distortion_type, self.ui.pinhole_correction_type]
        with block_signals(*widgets):
            if v is None:
                self.ui.distortion_type.setCurrentText('Offset')
                idx = self.ui.distortion_type.currentIndex()
                self.ui.distortion_tab_widget.setCurrentIndex(idx)
                return

            self.ui.distortion_type.setCurrentText('Pinhole Camera Correction')
            idx = self.ui.distortion_type.currentIndex()
            self.ui.distortion_tab_widget.setCurrentIndex(idx)

            conversions = {
                'SampleLayerDistortion': 'Sample Layer',
                'PinholeDistortion': 'Pinhole',
            }
            if v in conversions:
                v = conversions[v]

            self.ui.pinhole_correction_type.setCurrentText(v)
            idx = self.ui.pinhole_correction_type.currentIndex()
            self.ui.pinhole_correction_type_tab_widget.setCurrentIndex(idx)

    @property
    def distortion_kwargs_config(self):
        if self.overlay is None:
            return

        return self.overlay.tth_distortion_kwargs

    @distortion_kwargs_config.setter
    def distortion_kwargs_config(self, v):
        if self.overlay is None:
            return

        if self.overlay.tth_distortion_kwargs == v:
            return

        self.overlay.tth_distortion_kwargs = v
        HexrdConfig().overlay_distortions_modified.emit(self.overlay.name)

    @property
    def distortion_kwargs_gui(self):
        dtype = self.distortion_type_gui
        if dtype is None:
            return None
        elif dtype == 'SampleLayerDistortion':
            return {
                'layer_standoff': self.ui.sl_layer_standoff.value() * 1e-3,
                'layer_thickness': self.ui.sl_layer_thickness.value() * 1e-3,
                'pinhole_thickness': (
                    self.ui.sl_pinhole_thickness.value() * 1e-3),
            }
        elif dtype == 'PinholeDistortion':
            return {
                'pinhole_radius': self.ui.ph_radius.value() * 1e-3,
                'pinhole_thickness': self.ui.ph_thickness.value() * 1e-3,
            }

        raise Exception(f'Not implemented for: {dtype}')

    @distortion_kwargs_gui.setter
    def distortion_kwargs_gui(self, v):
        # Values are (key, default)
        values = {
            'sl_layer_standoff': ('layer_standoff', 0.15),
            'sl_layer_thickness': ('layer_thickness', 0.005),
            'sl_pinhole_thickness': ('pinhole_thickness', 0.1),
            'ph_radius': ('pinhole_radius', 0.1),
            'ph_thickness': ('pinhole_thickness', 0.1),
        }

        dtype = self.distortion_type_gui
        if dtype == 'SampleLayerDistortion':
            widget_prefix = 'sl_'
        elif dtype == 'PinholeDistortion':
            widget_prefix = 'ph_'
        elif dtype is None:
            widget_prefix = '_'
        else:
            raise Exception(f'Not implemented for: {dtype}')

        for w_name, (key, value) in values.items():
            if w_name.startswith(widget_prefix):
                # Extract the value from the dict
                value = v.get(key, value)

            w = getattr(self.ui, w_name)
            w.setValue(value * 1e3)

    @property
    def offset_widgets(self):
        return [getattr(self.ui, f'offset_{i}') for i in range(3)]

    @property
    def sample_layer_widgets(self):
        widgets = [
            'sl_layer_standoff',
            'sl_layer_thickness',
            'sl_pinhole_thickness',
        ]
        return [getattr(self.ui, w) for w in widgets]

    @property
    def pinhole_widgets(self):
        return [self.ui.ph_radius, self.ui.ph_thickness]

    @property
    def widgets(self):
        distortion_widgets = (
            self.offset_widgets +
            self.sample_layer_widgets +
            self.pinhole_widgets +
            [self.ui.distortion_type, self.ui.pinhole_correction_type]
        )
        return [
            self.ui.enable_width,
            self.ui.tth_width
        ] + distortion_widgets

    def material_tth_width_modified_externally(self, material_name):
        if not self.material:
            return

        if material_name != self.material.name:
            return

        self.update_gui()

    def update_reflections_table(self):
        if hasattr(self, '_table'):
            self._table.material = self.material

    def show_reflections_table(self):
        if not hasattr(self, '_table'):
            kwargs = {
                'material': self.material,
                'parent': self.ui,
            }
            self._table = ReflectionsTable(**kwargs)
        else:
            # Make sure the material is up to date
            self._table.material = self.material

        self._table.show()

    @property
    def distortion_type(self):
        return self.ui.distortion_type.currentText()

    @property
    def pinhole_correction_type(self):
        return self.ui.pinhole_correction_type.currentText()

    @pinhole_correction_type.setter
    def pinhole_correction_type(self, v):
        self.ui.pinhole_correction_type.setCurrentText(v)

    def distortion_type_changed(self):
        self.validate_distortion_type()
        self.update_config()

    def validate_distortion_type(self):
        if self.distortion_type == 'Pinhole Camera Correction':
            # Warn the user if there is a non-zero oscillation stage vector
            stage = HexrdConfig().instrument_config['oscillation_stage']
            if not np.all(np.isclose(stage['translation'], 0)):
                msg = (
                    'WARNING: a non-zero oscillation stage vector is being '
                    'used with the Pinhole Camera Correction.'
                )
                QMessageBox.critical(self.ui, 'HEXRD', msg)

            # FIXME: do we need to produce this warning for PinholeDistortion?
            beam = HexrdConfig().instrument_config['beam']
            source_distance = beam.get('source_distance', np.inf)
            if source_distance is None or source_distance == np.inf:
                msg = (
                    'WARNING: the source distance is infinite.\n\nThe '
                    'Pinhole Camera Correction will have no effect '
                    'unless the source distance is finite.\n\nThe source '
                    'distance may be edited in the Instrument "Form View"'
                )
                QMessageBox.critical(self.ui, 'HEXRD', msg)
