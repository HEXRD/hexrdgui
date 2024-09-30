import copy

import numpy as np

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.pinhole_correction_editor import PinholeCorrectionEditor
from hexrdgui.reflections_table import ReflectionsTable
from hexrdgui.select_items_widget import SelectItemsWidget
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals
from hexrdgui.utils.physics_package import (
    ask_to_create_physics_package_if_missing,
)


class PowderOverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('powder_overlay_editor.ui', parent)

        self._overlay = None

        self.pinhole_correction_editor = PinholeCorrectionEditor(self.ui)
        pinhole_editor = self.pinhole_correction_editor
        self.ui.distortion_pinhole_correction_layout.addWidget(
            pinhole_editor.ui)
        pinhole_editor.rygg_absorption_length_visible = False
        pinhole_editor.none_option_visible = False

        self.refinements_selector = SelectItemsWidget([], self.ui)
        self.ui.refinements_selector_layout.addWidget(
            self.refinements_selector.ui)

        self.update_visibility_states()
        self.setup_connections()

    def setup_connections(self):
        for w in self.widgets:
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self.update_config)

        self.pinhole_correction_editor.settings_modified.connect(
            self.update_config)

        self.ui.enable_width.toggled.connect(self.update_enable_states)
        self.refinements_selector.selection_changed.connect(
            self.update_refinements)

        self.ui.reflections_table.pressed.connect(self.show_reflections_table)

        HexrdConfig().material_tth_width_modified.connect(
            self.material_tth_width_modified_externally)

        self.ui.distortion_type.currentIndexChanged.connect(
            self.distortion_type_changed)

        HexrdConfig().instrument_config_loaded.connect(
            self.update_visibility_states)

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

    def update_visibility_states(self):
        label = self.ui.xray_source_label
        combo = self.ui.xray_source

        visible = HexrdConfig().has_multi_xrs
        label.setVisible(visible)
        combo.setVisible(visible)

    def update_enable_states(self):
        enable_width = self.ui.enable_width.isChecked()
        self.ui.tth_width.setEnabled(enable_width)

    def update_gui(self):
        if self.overlay is None:
            return

        with block_signals(*self.widgets):
            self.ui.xray_source.clear()
            if HexrdConfig().has_multi_xrs:
                self.ui.xray_source.addItems(HexrdConfig().beam_names)

            self.tth_width_gui = self.tth_width_config
            self.offset_gui = self.offset_config
            self.distortion_type_gui = self.distortion_type_config
            self.distortion_kwargs_gui = self.distortion_kwargs_config
            self.refinements_with_labels = self.overlay.refinements_with_labels
            self.clip_with_panel_buffer_gui = (
                self.clip_with_panel_buffer_config)
            self.xray_source_gui = self.xray_source_config

            self.update_enable_states()
            self.update_reflections_table()

    def update_config(self):
        self.tth_width_config = self.tth_width_gui
        self.offset_config = self.offset_gui
        self.distortion_config = self.distortion_gui
        self.clip_with_panel_buffer_config = self.clip_with_panel_buffer_gui
        self.xray_source_config = self.xray_source_gui

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

        return self.pinhole_correction_editor.correction_type

    @distortion_type_gui.setter
    def distortion_type_gui(self, v):
        widgets = [self.ui.distortion_type, self.pinhole_correction_editor]
        with block_signals(*widgets):
            if v is None:
                self.ui.distortion_type.setCurrentText('Offset')
                idx = self.ui.distortion_type.currentIndex()
                self.ui.distortion_tab_widget.setCurrentIndex(idx)
                return

            self.ui.distortion_type.setCurrentText('Pinhole Camera Correction')
            idx = self.ui.distortion_type.currentIndex()
            self.ui.distortion_tab_widget.setCurrentIndex(idx)

            self.pinhole_correction_editor.correction_type = v

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

        return self.pinhole_correction_editor.correction_kwargs

    @distortion_kwargs_gui.setter
    def distortion_kwargs_gui(self, v):
        self.pinhole_correction_editor.correction_kwargs = v

    @property
    def distortion_config(self):
        return self.distortion_type_config, self.distortion_kwargs_config

    @distortion_config.setter
    def distortion_config(self, v):
        if self.overlay is None:
            return

        dtype, dconfig = v
        if (self.overlay.tth_distortion_type == dtype and
                self.overlay.tth_distortion_kwargs == dconfig):
            return

        self.overlay.tth_distortion_type = dtype
        self.overlay.tth_distortion_kwargs = dconfig
        HexrdConfig().overlay_distortions_modified.emit(self.overlay.name)

    @property
    def distortion_gui(self):
        return self.distortion_type_gui, self.distortion_kwargs_gui

    @distortion_gui.setter
    def distortion_gui(self, v):
        self.distortion_type_gui = v[0]
        self.distortion_type_kwargs = v[1]

    @property
    def offset_widgets(self):
        return [getattr(self.ui, f'offset_{i}') for i in range(3)]

    @property
    def widgets(self):
        distortion_widgets = (
            self.offset_widgets +
            [self.ui.distortion_type, self.pinhole_correction_editor]
        )
        return [
            self.ui.enable_width,
            self.ui.tth_width,
            self.ui.clip_with_panel_buffer,
            self.ui.xray_source,
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
        return self.pinhole_correction_editor.correction_type

    @pinhole_correction_type.setter
    def pinhole_correction_type(self, v):
        self.pinhole_correction_editor.correction_type = v

    @property
    def xray_source_config(self) -> str | None:
        if self.overlay is None or not HexrdConfig().has_multi_xrs:
            return None

        return self.overlay.xray_source

    @xray_source_config.setter
    def xray_source_config(self, v: str | None):
        if v is not None and not HexrdConfig().has_multi_xrs:
            raise Exception(v)

        self.overlay.xray_source = v

    @property
    def xray_source_gui(self):
        if not HexrdConfig().has_multi_xrs:
            return None

        w = self.ui.xray_source
        idx = w.currentIndex()
        return w.currentText()

    @xray_source_gui.setter
    def xray_source_gui(self, v):
        if v is not None and not HexrdConfig().has_multi_xrs:
            raise Exception(v)

        w = self.ui.xray_source
        if v is None:
            w.setCurrentIndex(0)
            return

        w.setCurrentText(v)

    def distortion_type_changed(self):
        if self.distortion_type == 'Pinhole Camera Correction':
            # A physics package is required for this operation
            if not ask_to_create_physics_package_if_missing():
                # Switch back to offset.
                self.distortion_type_gui = None
                return

            if self.pinhole_correction_type is None:
                # Since we hide None, let's switch to sample layer offset
                self.pinhole_correction_type = 'SampleLayerDistortion'

        self.update_config()

    @property
    def clip_with_panel_buffer_config(self):
        if self.overlay is None:
            return False

        return self.overlay.clip_with_panel_buffer

    @clip_with_panel_buffer_config.setter
    def clip_with_panel_buffer_config(self, b):
        if self.overlay is None:
            return

        self.overlay.clip_with_panel_buffer = b

    @property
    def clip_with_panel_buffer_gui(self):
        return self.ui.clip_with_panel_buffer.isChecked()

    @clip_with_panel_buffer_gui.setter
    def clip_with_panel_buffer_gui(self, b):
        self.ui.clip_with_panel_buffer.setChecked(b)
